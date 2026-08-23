#!/usr/bin/env python3
# 本地后端：托管 dist/ 静态站点，并提供分类树持久化 API。
# 仅用于本机运行（python server.py），不做真实 AI 调用。
import os, re, sys, json, subprocess, urllib.parse, importlib.util, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
CONTENT = os.path.join(ROOT, "content")
CATFILE = os.path.join(ROOT, "categories.json")
PORT = int(os.environ.get("PORT", "8766"))

# 引入 build.py 以便触发重建
spec = importlib.util.spec_from_file_location("kbbuild", os.path.join(ROOT, "build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

def read_categories():
    try:
        return json.load(open(CATFILE, encoding="utf-8"))
    except Exception:
        return []

def write_categories(cats):
    # 原子写：先写临时文件再替换，避免写一半进程被杀导致 categories.json 损坏
    tmp = CATFILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cats, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CATFILE)

def slug_to_path(slug):
    if slug.startswith("papers_"):
        p = os.path.join(CONTENT, "papers", slug[len("papers_"):] + ".md")
    elif slug.startswith("notes_"):
        p = os.path.join(CONTENT, "notes", slug[len("notes_"):] + ".md")
    else:
        return None
    p = os.path.abspath(p)
    if not p.startswith(os.path.abspath(CONTENT)):
        return None
    return p if os.path.exists(p) else None

def slug_to_file(slug):
    """返回 slug 对应的文件路径（不检查是否存在），用于新建条目。"""
    if slug.startswith("papers_"):
        return os.path.join(CONTENT, "papers", slug[len("papers_"):] + ".md")
    if slug.startswith("notes_"):
        return os.path.join(CONTENT, "notes", slug[len("notes_"):] + ".md")
    return None

def _quote_val(v):
    v = "" if v is None else str(v)
    if v == "":
        return '""'
    if re.search(r'[:#"]|\s$|^\s', v):
        v = v.replace('"', '\\"')
        return '"' + v + '"'
    return v

def fmt_fm_pair(key, val):
    """生成 frontmatter 中某键值对应的行。列表（tags/authors 等）输出为 YAML
    内联列表 `key: ["a", "b"]`；普通值一行；含换行（如长摘要）用 YAML
    字面量块 `key: |-` 保留多行，避免摘要被压成一行或破坏 YAML。"""
    if isinstance(val, (list, tuple)):
        if not val:
            return [key + ": []"]
        inner = ", ".join(_quote_val(str(x)) for x in val)
        return [key + ": [" + inner + "]"]
    val = "" if val is None else str(val)
    if "\n" in val:
        out = [key + ": |-"]
        for ln in val.split("\n"):
            out.append("  " + ln)
        return out
    return [key + ": " + _quote_val(val)]

def rewrite_entry(slug, title, body, meta):
    """重写某条目的 frontmatter（仅改 title 与给定 meta，其余字段及顺序原样保留），
    再把正文替换为传入的 body。parent_paper 等数据字段不在 meta 中即自动保留。"""
    path = slug_to_path(slug)
    if not path:
        return False, "entry not found: %s" % slug
    raw = open(path, encoding="utf-8").read()
    has_fm = raw.startswith("---")
    if has_fm:
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm_block = parts[1].strip("\n")
        else:
            fm_block, has_fm = "", False  # 形如 '---' 但不完整，退化为无 frontmatter
    else:
        fm_block = ""
    if has_fm:
        new_lines = []
        seen = set()
        lines = fm_block.split("\n")
        i = 0
        in_block = False  # 上一个键被重写为多行块标量时，其后的缩进续行（畸形原文件常见）应跳过
        while i < len(lines):
            ln = lines[i]
            if ln.strip().startswith("#"):
                new_lines.append(ln); in_block = False; i += 1; continue
            m = re.match(r"^([A-Za-z\u4e00-\u9fff_\-]+):\s?(.*)$", ln)
            if m:
                key = m.group(1); val = m.group(2).strip(); seen.add(key)
                in_block = False
                # 块标量（key: | / |- / > / >-）：原值占用多行续行
                if re.match(r"^[|>][-+]?$", val):
                    if key == "title":
                        new_lines.extend(fmt_fm_pair("title", title))
                    elif key in meta:
                        new_lines.extend(fmt_fm_pair(key, meta[key]))
                    else:
                        new_lines.append(ln)  # 保留 key: |- 行
                    # 跳过/保留续行：重写（title 或 meta 命中）时丢弃原续行，避免污染新块；
                    # 仅保留模式才把原续行也原样追加
                    i += 1
                    while i < len(lines) and (lines[i] == "" or lines[i].startswith("  ")):
                        if not (key == "title" or key in meta):
                            new_lines.append(lines[i])
                        i += 1
                    continue
                # 普通单行值
                if key == "title":
                    new_lines.extend(fmt_fm_pair("title", title))
                elif key in meta:
                    new_lines.extend(fmt_fm_pair(key, meta[key]))
                    if "\n" in meta[key]:
                        in_block = True  # 刚写出的块标量，其后的缩进续行应跳过
                else:
                    new_lines.append(ln)
                i += 1
            else:
                # 键不匹配：可能是上一块标量的缩进续行（畸形原文件），跳过；
                # 也可能是列表项（- 开头，列 0）或空行，保留。
                if in_block and (ln.startswith("  ") or ln == ""):
                    i += 1; continue
                new_lines.append(ln); i += 1
        for k, v in meta.items():
            if k not in seen:
                new_lines.extend(fmt_fm_pair(k, v))
        # 关键：正文必须用传入的 body 覆盖，而非保留原始 rest
        new_raw = "---\n" + "\n".join(new_lines) + "\n---\n" + (body or "")
    else:
        # 原本无 frontmatter：不强行加 frontmatter，仅替换正文，保留原元数据改动仅限 body
        new_raw = (body or raw)
    open(path, "w", encoding="utf-8").write(new_raw)
    return True, None

def set_entry_category(slug, cat_id):
    p = slug_to_path(slug)
    if not p:
        return False
    t = open(p, encoding="utf-8").read()
    nt = re.sub(r"^category:.*$", "category: %s" % cat_id, t, count=1, flags=re.M)
    open(p, "w", encoding="utf-8").write(nt)
    return nt != t

def gen_id(name):
    base = re.sub(r"[^\w一-鿿]+", "_", name).strip("_").lower() or "cat"
    cats = read_categories()
    ids = {c["id"] for c in cats}
    cand = base
    i = 1
    while cand in ids:
        cand = "%s_%d" % (base, i)
        i += 1
    return cand

def rebuild():
    try:
        build.main()
        return True
    except Exception as e:
        sys.stderr.write("rebuild error: %s\n" % e)
        return False

def state_payload():
    data = json.load(open(os.path.join(DIST, "index.json"), encoding="utf-8"))
    return {"entries": data.get("entries", []), "categories": read_categories()}

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, body=None, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if obj is not None:
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        elif body is not None:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        if path == "/" or path == "/index.html":
            return self._static("/index.html")
        if path == "/api/state":
            return self._send(200, state_payload())
        if path == "/api/entry/raw":
            return self.api_entry_raw(u)
        if path == "/api/skill/raw":
            return self.api_skill_raw(u)
        # 静态资源
        if path.startswith("/assets/") or path.startswith("/entries/") or path == "/index.json":
            return self._static(path)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        try:
            ln = int(self.headers.get("Content-Length", 0) or 0)
            # rfile.read() may return a short read; loop until we have all bytes.
            raw = b""
            while len(raw) < ln:
                chunk = self.rfile.read(ln - len(raw))
                if not chunk:
                    break
                raw += chunk
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                try:
                    payload = json.loads(raw.decode("gbk", "replace")) if raw else {}
                except Exception:
                    payload = {}
        except Exception:
            payload = {}
        return self.handle_api(u.path, payload)

    def handle_api(self, path, p):
        try:
            return self._dispatch(path, p)
        except Exception as e:
            import traceback as _tb
            sys.stderr.write("API ERROR %s:\n%s\n" % (path, _tb.format_exc()))
            try:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            except Exception:
                pass

    def _dispatch(self, path, p):
        if path == "/api/rebuild":
            ok = rebuild()
            return self._send(200, {"ok": ok, **state_payload()})
        if path == "/api/category":
            return self.api_category(p)
        if path == "/api/entry/category":
            slug = p.get("slug", "")
            cid = p.get("category", "")
            if not slug or not cid:
                return self._send(400, {"error": "slug/category required"})
            changed = set_entry_category(slug, cid)
            rebuild()
            return self._send(200, {"changed": changed, **state_payload()})
        if path == "/api/import-rdf":
            return self.api_import_rdf(p)
        if path == "/api/entry/update":
            return self.api_entry_update(p)
        if path == "/api/entry/create":
            return self.api_entry_create(p)
        if path == "/api/entry/delete":
            return self.api_entry_delete(p)
        if path == "/api/skill/update":
            return self.api_skill_update(p)
        return self._send(404, {"error": "unknown api"})

    def api_entry_raw(self, u):
        q = urllib.parse.parse_qs(u.query)
        slug = (q.get("slug") or [""])[0]
        p = slug_to_path(slug)
        if not p:
            return self._send(404, {"error": "entry not found: %s" % slug})
        try:
            raw = open(p, encoding="utf-8").read()
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(200, {"slug": slug, "raw": raw})

    def api_entry_update(self, p):
        slug = p.get("slug", "")
        title = (p.get("title") or "").strip()
        body = p.get("body", "")
        meta = p.get("meta") or {}
        if not slug:
            return self._send(400, {"error": "slug required"})
        ok, err = rewrite_entry(slug, title, body, meta)
        if not ok:
            return self._send(404, {"error": err})
        try:
            rebuild()
            return self._send(200, {"ok": True, **state_payload()})
        except Exception as e:
            sys.stderr.write("entry update error: %s\n" % e)
            return self._send(500, {"error": str(e)})

    def api_entry_create(self, p):
        kind = (p.get("kind") or "").strip()
        if kind not in ("paper", "note"):
            return self._send(400, {"error": "kind must be paper or note"})
        title = (p.get("title") or "").strip()
        if not title:
            return self._send(400, {"error": "title required"})
        body = p.get("body") or ""
        meta = p.get("meta") or {}
        parent_paper = (p.get("parent_paper") or "").strip() or None
        category = (p.get("category") or "").strip() or None
        stamp = str(int(time.time()))[-7:]
        base = re.sub(r"[^\w一-鿿]+", "_", title).strip("_").lower() or "entry"
        prefix = "papers_" if kind == "paper" else "notes_"
        slug = "%s%s_manual_%s" % (prefix, base, stamp)
        while slug_to_file(slug) and os.path.exists(slug_to_file(slug)):
            stamp = str(int(time.time() * 1000))[-8:]
            slug = "%s%s_manual_%s" % (prefix, base, stamp)
        fm = {"title": title, "kind": kind}
        if category:
            fm["category"] = category
        if parent_paper:
            fm["parent_paper"] = parent_paper
        if meta.get("tags"):
            fm["tags"] = meta["tags"]
        for k in ("journal", "date", "created", "pdf", "source", "doi", "summary"):
            if meta.get(k):
                fm[k] = meta[k]
        # 创建时间 = 录入时间（默认当前时间，精确到分）；仅当用户未显式提供时才自动盖章
        if "created" not in fm:
            fm["created"] = time.strftime("%Y-%m-%d %H:%M")
        lines = ["---"]
        for k, v in fm.items():
            lines.extend(fmt_fm_pair(k, v))
        lines.append("---")
        raw = "\n".join(lines) + "\n" + (body or "") + "\n"
        path = slug_to_file(slug)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(raw)
        except Exception as e:
            return self._send(500, {"error": "write failed: %s" % e})
        rebuild()
        return self._send(200, {"slug": slug, **state_payload()})

    def api_entry_delete(self, p):
        slug = (p.get("slug") or "").strip()
        if not slug:
            return self._send(400, {"error": "slug required"})
        path = slug_to_path(slug)
        if not path:
            return self._send(404, {"error": "entry not found: %s" % slug})
        try:
            os.remove(path)
        except Exception as e:
            return self._send(500, {"error": "delete failed: %s" % e})
        rebuild()
        return self._send(200, {"slug": slug, **state_payload()})

    # --- skill API ---
    SKILL_DIRS = [
        os.path.join(ROOT, ".workbuddy", "skills"),
        os.path.join(os.path.expanduser("~"), ".workbuddy", "skills"),
    ]

    def _skill_path(self, name):
        for d in self.SKILL_DIRS:
            p = os.path.join(d, name, "SKILL.md")
            if os.path.isfile(p):
                return p
        return None

    def api_skill_raw(self, u):
        q = urllib.parse.parse_qs(u.query)
        name = (q.get("name") or [""])[0]
        if not name:
            return self._send(400, {"error": "name required"})
        p = self._skill_path(name)
        if not p:
            return self._send(404, {"error": "skill not found: %s" % name})
        try:
            raw = open(p, "r", encoding="utf-8").read()
            return self._send(200, {"name": name, "content": raw, "path": p})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def api_skill_update(self, p):
        name = (p.get("name") or "").strip()
        content = p.get("content") or ""
        if not name:
            return self._send(400, {"error": "name required"})
        fpath = self._skill_path(name)
        if not fpath:
            return self._send(404, {"error": "skill not found: %s" % name})
        try:
            open(fpath, "w", encoding="utf-8").write(content)
            return self._send(200, {"name": name, "ok": True})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def api_import_rdf(self, p):
        import importlib
        path = (p.get("path") or os.path.join(ROOT, "PhD文献.rdf")).strip()
        if not os.path.exists(path):
            return self._send(404, {"error": "未找到 RDF 文件：%s" % path})
        try:
            spec = importlib.util.spec_from_file_location("import_rdf_mod",
                                                          os.path.join(ROOT, "import_rdf.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.RDF_PATH = path          # 覆盖导入源
            mod.main()                    # 重建分类树 + 导入文献/笔记 + build
            return self._send(200, {"ok": True, "file": path, **state_payload()})
        except Exception as e:
            sys.stderr.write("import-rdf error: %s\n" % e)
            return self._send(500, {"error": str(e)})

    def api_category(self, p):
        action = p.get("action")
        cats = read_categories()
        idmap = {c["id"]: c for c in cats}
        if action == "create":
            name = (p.get("name") or "").strip()
            parent = p.get("parent") or None
            if not name:
                return self._send(400, {"error": "name required"})
            if parent and parent not in idmap:
                return self._send(400, {"error": "parent not found"})
            cid = gen_id(name)
            cats.append({"id": cid, "name": name, "parent": parent})
            write_categories(cats)
            rebuild()
            return self._send(200, {"id": cid, **state_payload()})
        if action == "update":
            cid = p.get("id")
            if cid not in idmap:
                return self._send(404, {"error": "not found"})
            if p.get("name") is not None:
                idmap[cid]["name"] = p["name"].strip()
            if "parent" in p:
                np = p["parent"] or None
                if np == cid:
                    return self._send(400, {"error": "cannot be own parent"})
                # 防止成环
                cur = idmap.get(np) if np else None
                while cur:
                    if cur["id"] == cid:
                        return self._send(400, {"error": "cycle detected"})
                    cur = idmap.get(cur.get("parent")) if cur.get("parent") else None
                idmap[cid]["parent"] = np
            write_categories(cats)
            rebuild()
            return self._send(200, state_payload())
        if action == "delete":
            cid = p.get("id")
            if cid not in idmap:
                return self._send(404, {"error": "not found"})
            if cid == "uncat":
                return self._send(400, {"error": "cannot delete 待归类"})
            # 子节点上提到被删节点的父级；条目归到父级或 uncat
            fallback = idmap[cid].get("parent") or "uncat"
            for c in cats:
                if c.get("parent") == cid:
                    c["parent"] = fallback
            cats = [c for c in cats if c["id"] != cid]
            write_categories(cats)
            # 把该分类下的论文改到 fallback
            data = json.load(open(os.path.join(DIST, "index.json"), encoding="utf-8"))
            for e in data.get("entries", []):
                if e.get("type") == "paper" and e.get("category") == cid:
                    set_entry_category(e["slug"], fallback)
            rebuild()
            return self._send(200, state_payload())
        return self._send(400, {"error": "unknown action"})

    def _static(self, rel):
        # 防目录穿越
        rel = rel.lstrip("/")
        full = os.path.normpath(os.path.join(DIST, rel))
        if not full.startswith(DIST) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = "text/html; charset=utf-8"
        if rel.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif rel.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif rel.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        self._send(200, body=open(full, "rb").read(), ctype=ctype)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    os.chdir(ROOT)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("KB site running at http://localhost:%d  (Ctrl+C to stop)" % PORT)
    srv.serve_forever()
