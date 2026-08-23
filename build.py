import os, re, json, shutil
import markdown
try:
    import yaml
except ImportError:
    yaml = None

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content")
TEMPL = os.path.join(ROOT, "templates")
DIST = os.path.join(ROOT, "dist")
ASSETS = os.path.join(DIST, "assets")
CATFILE = os.path.join(ROOT, "categories.json")

ENTRY_TPL = open(os.path.join(TEMPL, "entry.html"), encoding="utf-8").read()
INDEX_TPL = open(os.path.join(TEMPL, "index.html"), encoding="utf-8").read()

# ---- 分类树 ----
def load_categories():
    try:
        return json.load(open(CATFILE, encoding="utf-8"))
    except Exception:
        return [{"id": "uncat", "name": "待归类", "parent": None}]

CATS = load_categories()
CATMAP = {c["id"]: c for c in CATS}

def cat_path(cid):
    """返回 'AIforBio / 应用类' 形式；找不到则返回原始串。"""
    if cid in CATMAP:
        chain = []
        cur = CATMAP[cid]
        guard = 0
        while cur and guard < 10:
            chain.insert(0, cur["name"])
            pid = cur.get("parent")
            cur = CATMAP.get(pid) if pid else None
            guard += 1
        return " / ".join(chain)
    return cid

def parse_fm(text):
    """解析 YAML frontmatter。优先用 yaml，失败（如标题含冒号 'Cell Decoder: ...'）
    则退回行级手动解析，避免整段 frontmatter 被静默丢弃。"""
    fm, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return fm, body
    body = text[m.end():]
    fm_raw = m.group(1)
    if yaml:
        try:
            fm = yaml.safe_load(fm_raw) or {}
            if isinstance(fm, dict):
                return fm, body
        except Exception:
            pass
    # 手动兜底：处理 标题含冒号 / 内联列表 [a, b] / 块标量(多行摘要)
    fm = {}
    lines = fm_raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1; continue
        if line.lstrip().startswith("- "):
            i += 1; continue
        if ":" not in line:
            i += 1; continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        # YAML 块标量：key: | / |- / > / >- （多行值）
        if re.match(r"^[|>][-+]?$", v):
            i += 1
            buf = []
            while i < len(lines) and (lines[i] == "" or lines[i].startswith("  ")):
                buf.append(lines[i][2:] if lines[i].startswith("  ") else "")
                i += 1
            fm[k] = "\n".join(buf)
            continue
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            fm[k] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()] if inner else []
        else:
            fm[k] = v.strip('"').strip("'")
        i += 1
    return fm, body

def render(body, kind=None, title=None):
    # 笔记正文：去掉开头所有与 frontmatter 标题重复的 # Title（可能多次出现）
    if kind == "note" and title and body:
        t = re.escape(title.strip())
        body = body.lstrip("\n")
        body = re.sub(r'^(?:#\s+' + t + r'\s*\n)+', '', body)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    return md.convert(body)

def esc(s):
    return (s if isinstance(s, str) else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def meta_html(fm):
    parts = []
    for k in ["category", "journal", "date", "source"]:
        v = fm.get(k)
        if v:
            parts.append('<span class="m"><b>%s</b>: %s</span>' % (k, esc(str(v))))
    return "".join(parts)

def main():
    if os.path.exists(DIST):
        try:
            shutil.rmtree(DIST)
        except Exception:
            # 沙箱/安全垫片可能拦截目录删除：退化为原地覆盖（残留旧 html 不影响使用）
            pass
    os.makedirs(ASSETS, exist_ok=True)
    entries = []
    for dp, _, fs in os.walk(CONTENT):
        for f in sorted(fs):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dp, f)
            text = open(p, encoding="utf-8").read()
            fm, body = parse_fm(text)
            slug = os.path.relpath(p, CONTENT)[:-3].replace(os.sep, "_").replace(" ", "_")
            title = fm.get("title") or os.path.splitext(f)[0]
            etype = fm.get("type", "paper")
            # kind: paper(顶层论文) / analysis(拆解，附属某论文) / note(笔记，附属某论文) / resource(独立知识资料)
            kind = fm.get("kind") or ("note" if etype == "note" else "paper")
            category = fm.get("category", "uncat")
            parent_paper = fm.get("parent_paper") or ""
            pdf = fm.get("pdf") or "无"
            # 论文必须落在分类树里；笔记/拆解/资料(category 不在树中)保留原值
            cat_name = CATMAP.get(category, {}).get("name", category) if kind == "paper" else category
            cat_path_val = cat_path(category) if kind == "paper" else category
            tags = fm.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            authors = fm.get("authors") or []
            if isinstance(authors, str):
                authors = [authors]
            date = str(fm.get("date", ""))
            created = str(fm.get("created") or "")  # 记录创建时间：仅取 frontmatter created，不回落到发表日期
            source = fm.get("source", "")
            journal = fm.get("journal", "")
            summary = fm.get("summary") or ""
            html = render(body, kind=kind, title=title)
            out_rel = slug + ".html"
            open(os.path.join(DIST, out_rel), "w", encoding="utf-8").write(
                ENTRY_TPL.replace("__TITLE__", esc(title))
                .replace("__META__", meta_html(fm))
                .replace("__BODY__", html)
            )
            entries.append({
                "slug": slug, "title": title, "type": kind, "kind": kind, "category": category,
                "parent_paper": parent_paper, "pdf": pdf,
                "catName": cat_name, "catPath": cat_path_val,
                "tags": tags, "authors": authors, "date": date, "created": created, "source": source,
                "journal": journal, "doi": fm.get("doi", ""), "summary": summary,
                "path": out_rel, "text": body, "html": html,
            })
    entries.sort(key=lambda e: (e["date"], e["title"]), reverse=True)
    out = {"entries": entries, "categories": CATS}
    json.dump(out, open(os.path.join(DIST, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(DIST, "index.html"), "w", encoding="utf-8").write(INDEX_TPL)
    for fn in ["style.css", "app.js", "marked.min.js"]:
        shutil.copyfile(os.path.join(ROOT, "assets", fn), os.path.join(ASSETS, fn))
    print("built %d entries -> %s" % (len(entries), DIST))

if __name__ == "__main__":
    main()
