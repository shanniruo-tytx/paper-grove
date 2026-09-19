#!/usr/bin/env python3
# 本地后端：托管 dist/ 静态站点，并提供分类树持久化 API。
# 仅用于本机运行（python server.py），不做真实 AI 调用。
import os, re, sys, json, subprocess, urllib.parse, urllib.request, importlib.util, time
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
    elif slug.startswith("resources_"):
        p = os.path.join(CONTENT, "resources", slug[len("resources_"):] + ".md")
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
    if slug.startswith("resources_"):
        return os.path.join(CONTENT, "resources", slug[len("resources_"):] + ".md")
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

def run_build_subprocess(timeout=600):
    """以子进程方式运行 build.py（lint_kb + gate_v2 硬闸）。

    不用 build.main() 直接调用：build.py 在 lint/gate 失败时会 sys.exit(1)，
    而 SystemExit 不是 Exception 的子类，会在请求线程里向上冒泡导致 500 甚至
    服务线程异常。子进程隔离后，失败只体现在返回码，服务主进程稳健。
    返回 (exit_code, combined_log)。"""
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "build.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
        log = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, log
    except subprocess.TimeoutExpired as e:
        out = getattr(e, "stdout", "") or ""
        err = getattr(e, "stderr", "") or ""
        return 124, (out + err + "\n[build timeout after %ds]\n" % timeout)
    except Exception as e:
        return 1, "build launch error: %s" % e

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
        if path == "/api/ingest":
            return self.api_ingest(p)
        if path == "/api/build":
            return self.api_build(p)
        if path == "/api/rebuild":
            code, log = run_build_subprocess()
            return self._send(200, {"ok": code == 0, "exit": code, "log_tail": log[-2000:], **state_payload()})
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
        if path == "/api/hub/sync":
            return self.api_hub_sync(p)
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
        """写入接口（agent「反向代理」落库的统一入口）。

        支持 kind ∈ {paper, note, resource}：
          - paper / note -> content/{papers,notes}/
          - resource     -> content/resources/（独立知识资料，category 强制 uncat，禁 parent_paper）
        可选显式 slug（如 papers_epibench_论文 / resources_cell_reference_mapping_weixin）；
        不提供时按标题自动生成 `*{prefix}{base}_manual_{stamp}`（兼容旧 UI 手动新建）。
        frontmatter 由 meta + 顶层字段组装，body 为 markdown 正文（不含 frontmatter）。
        写入后自动 rebuild()（含 lint_kb + gate_v2 硬闸），失败会在响应中回显。
        """
        kind = (p.get("kind") or "").strip()
        if kind not in ("paper", "note", "resource"):
            return self._send(400, {"error": "kind must be paper/note/resource"})
        prefix = {"paper": "papers_", "note": "notes_", "resource": "resources_"}[kind]
        title = (p.get("title") or "").strip()
        body = p.get("body") or ""
        meta = p.get("meta") or {}
        req_slug = (p.get("slug") or "").strip()

        if req_slug:
            if not req_slug.startswith(prefix):
                return self._send(400, {"error": "slug 必须以 %s 开头" % prefix})
            if not re.match(r"^[A-Za-z0-9_一-鿿\-]+$", req_slug):
                return self._send(400, {"error": "slug 含非法字符"})
            slug = req_slug
        else:
            if not title:
                return self._send(400, {"error": "title 必填（或显式提供 slug）"})
            stamp = str(int(time.time()))[-7:]
            base = re.sub(r"[^\w一-鿿]+", "_", title).strip("_").lower() or "entry"
            slug = "%s%s_manual_%s" % (prefix, base, stamp)
            while slug_to_file(slug) and os.path.exists(slug_to_file(slug)):
                stamp = str(int(time.time() * 1000))[-8:]
                slug = "%s%s_manual_%s" % (prefix, base, stamp)

        fm = {}
        if title:
            fm["title"] = title
        fm["kind"] = kind
        # 分类：resource 强制 uncat（资源不参与文献库分类树）
        category = (p.get("category") or meta.get("category") or "").strip() or None
        if kind == "resource":
            fm["category"] = category or "uncat"
        elif category:
            fm["category"] = category
        # parent_paper：resource 禁止挂载（破坏「只在知识库」隔离）
        parent_paper = (p.get("parent_paper") or meta.get("parent_paper") or "").strip() or None
        if parent_paper and kind != "resource":
            fm["parent_paper"] = parent_paper
        # 其余 frontmatter 字段：顶层优先，其次 meta
        for k in ("journal", "date", "created", "pdf", "source", "doi",
                  "summary", "一句话概括", "doc_type", "note_type",
                  "pipeline_version", "tags", "authors", "type"):
            v = p.get(k)
            if v is None:
                v = meta.get(k)
            if k in ("tags", "authors") and isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if v:
                fm[k] = v
        if kind == "note" and "type" not in fm:
            fm["type"] = "note"
        # 创建时间：缺省盖章当前时间（精确到分）
        if "created" not in fm:
            fm["created"] = time.strftime("%Y-%m-%d %H:%M")

        lines = ["---"]
        for k, v in fm.items():
            lines.extend(fmt_fm_pair(k, v))
        lines.append("---")
        raw = "\n".join(lines) + "\n" + (body or "") + "\n"
        path = slug_to_file(slug)
        if not path:
            return self._send(400, {"error": "slug 无法映射到本地路径"})
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(raw)
        except Exception as e:
            return self._send(500, {"error": "write failed: %s" % e})
        rebuild()
        return self._send(200, {"slug": slug, **state_payload()})

    def api_ingest(self, p):
        """接口化导入入口（替代 Agent 直接本地写 content/*.md + 跑 build.py）。

        请求体：
        {
          "files": [
            {"path": "content/papers/alphagenome_atlas_论文.md", "content": "---\ntitle: ...\n---"},
            {"path": "content/notes/alphagenome_atlas_论文拆解.md", "content": "..."},
            ...
          ],
          "build": true            # 可选，默认 true：写完后立即跑 build.py 双闸
        }
        - path 仅允许 content/{papers,notes,resources}/<name>.md，禁止目录穿越与非 .md
        - content 为已成型 markdown（含 frontmatter），服务端原样落盘，不重建 frontmatter
        - 写盘用 temp+os.replace 原子替换；写完后按 build 触发 build.py（lint+gate 硬闸）
        - 返回写入清单 + 构建结果（exit/ok/log_tail），构建失败也不丢已写文件，便于修正重投
        """
        files = p.get("files")
        if not isinstance(files, list) or not files:
            return self._send(400, {"error": "'files' 必填且非空（数组）"})
        allowed_prefixes = ("content/papers/", "content/notes/", "content/resources/")
        written = []
        for item in files:
            if not isinstance(item, dict):
                return self._send(400, {"error": "files 每项须为对象 {path, content}"})
            rel = (item.get("path") or "").strip().replace("\\", "/").lstrip("/")
            content = item.get("content") or ""
            if not rel:
                return self._send(400, {"error": "每项需含 path"})
            if not rel.endswith(".md"):
                return self._send(400, {"error": "仅允许 .md 文件：%s" % rel})
            if not rel.startswith(allowed_prefixes):
                return self._send(400, {"error": "非法路径（仅允许 content/{papers,notes,resources}/...）：%s" % rel})
            # 允许子目录（如 content/resources/foo/bar.md）但必须仍落在 CONTENT 内
            full = os.path.normpath(os.path.join(ROOT, rel))
            content_root = os.path.normpath(CONTENT)
            if full != content_root and not full.startswith(content_root + os.sep):
                return self._send(400, {"error": "路径穿越被拒绝：%s" % rel})
            try:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                tmp = full + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp, full)
                written.append(rel)
            except Exception as e:
                return self._send(500, {"error": "写入 %s 失败：%s" % (rel, e)})
        do_build = p.get("build", True)
        build_exit = None
        build_ok = None
        build_log = ""
        if do_build:
            build_exit, build_log = run_build_subprocess()
            build_ok = build_exit == 0
        return self._send(200, {
            "ok": True,
            "written": written,
            "build": {"exit": build_exit, "ok": build_ok, "log_tail": build_log[-2000:]},
            **state_payload()
        })

    def api_build(self, p):
        """仅触发重新构建（不写新文件），等价于接口化版本的 '运行 build.py'。"""
        build_exit, build_log = run_build_subprocess()
        return self._send(200, {
            "ok": build_exit == 0,
            "exit": build_exit,
            "log_tail": build_log[-2000:],
            **state_payload()
        })

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

    def api_hub_sync(self, p):
        """从统一管理中心（Hub, 默认 http://127.0.0.1:4173）拉取 article-summarizer
        Harness 的 Skill / Prompt 文件，写回本机 kb-site 的执行副本，使本地 agent
        执行与 Hub 规范源保持一致。仅同步 kb-site 本地持有的文件，跳过用户级 paper-reader。"""
        harness = (p.get("harness") or "article-summarizer").strip()
        hub = (p.get("hub") or "http://127.0.0.1:4173").rstrip("/")
        url = "%s/api/harnesses/%s/files" % (hub, urllib.parse.quote(harness))
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._send(502, {"error": "无法从 Hub 拉取文件：%s" % e})
        files = payload.get("files") or []
        mapping = {
            "skills/article-summarizer.md": os.path.join(ROOT, ".workbuddy", "skills", "article-summarizer", "SKILL.md"),
            "skills/paper-locator.md": os.path.join(ROOT, ".workbuddy", "skills", "paper-locator", "SKILL.md"),
            "prompts/summary-format.md": os.path.join(ROOT, ".workbuddy", "skills", "article-summarizer", "summary-format.md"),
        }
        written = []
        for f in files:
            rel = f.get("path") or ""
            dst = mapping.get(rel)
            if not dst:
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                open(dst, "w", encoding="utf-8").write(f.get("content") or "")
                written.append(rel)
            except Exception as e:
                return self._send(500, {"error": "写入 %s 失败：%s" % (rel, e)})
        return self._send(200, {"ok": True, "written": written, "hub": hub, "harness": harness})

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
