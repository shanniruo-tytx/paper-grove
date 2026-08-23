#!/usr/bin/env python3
# 导入 Zotero CSV 导出（文献 + 笔记）到知识库平台。
# 注意：Zotero CSV 不含收藏目录列，故所有条目先归入「待归类」，由用户在界面/后续导入真实目录树后重新归档。
import os, re, csv, sys, io, json
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content", "papers")
NOTES = os.path.join(ROOT, "content", "notes")
CATFILE = os.path.join(ROOT, "categories.json")
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Administrator\Desktop\PhD文献.csv"

os.makedirs(CONTENT, exist_ok=True)
os.makedirs(NOTES, exist_ok=True)

def html2md(h):
    if not h:
        return ""
    h = re.sub(r"(?i)<h1[^>]*>", "\n# ", h)
    h = re.sub(r"(?i)<h2[^>]*>", "\n## ", h)
    h = re.sub(r"(?i)<h3[^>]*>", "\n### ", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"(?i)</?(p|div|br|ul|ol|blockquote)[^>]*>", "\n", h)
    h = re.sub(r"(?i)<[^>]+>", "", h)
    h = h.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    h = re.sub(r"\n{3,}", "\n\n", h).strip()
    return h

def slugify(s, maxlen=60):
    s = re.sub(r"[^\w一-鿿\-]+", "_", s).strip("_")
    return s[:maxlen] or "item"

def reset_existing():
    # 把已存在的论文分类重置为 uncat（旧树已废弃，等待用户真实目录）
    n = 0
    for f in os.listdir(CONTENT):
        if not f.endswith(".md"):
            continue
        p = os.path.join(CONTENT, f)
        t = open(p, encoding="utf-8").read()
        nt = re.sub(r"^category:.*$", "category: uncat", t, count=1, flags=re.M)
        if nt != t:
            open(p, "w", encoding="utf-8").write(nt)
            n += 1
    return n

def main():
    # 1) 重置分类树为最小（仅待归类）；用户可手动增删，自动入库不会新建
    json.dump([{"id": "uncat", "name": "待归类", "parent": None}],
              open(CATFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 2) 旧论文分类重置
    reset_n = reset_existing()

    # 3) 解析 CSV
    rows = []
    with io.open(CSV_PATH, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)
    print("CSV 读到 %d 条文献" % len(rows))

    imported = 0
    for r in rows:
        key = (r.get("Key") or "").strip()
        title = (r.get("Title") or "").strip()
        if not title:
            continue
        item_type = (r.get("Item Type") or "journalArticle").strip()
        if item_type.lower() == "note":
            # 独立笔记
            body = html2md(r.get("Note") or r.get("Notes") or "")
            fm = {"title": title, "type": "note", "category": "uncat",
                  "tags": split_tags(r.get("Manual Tags")), "date": (r.get("Date") or "")[:10]}
            out = os.path.join(NOTES, "zotero_%s.md" % slugify(title))
            write_md(out, fm, "# %s\n\n%s" % (title, body))
            imported += 1
            continue
        authors = [a.strip() for a in (r.get("Author") or "").split(";") if a.strip()]
        abstract = (r.get("Abstract Note") or "").strip()
        note = html2md(r.get("Notes") or "")
        date = (r.get("Date") or (r.get("Publication Year") or "")).strip()[:10]
        journal = (r.get("Publication Title") or "").strip()
        doi = (r.get("DOI") or "").strip()
        url = (r.get("Url") or "").strip()
        source = url or (("https://doi.org/" + doi) if doi else "")
        tags = split_tags(r.get("Manual Tags"))
        summary = abstract[:240].replace("\n", " ")
        slug = "zotero_%s_%s" % (key, slugify(title))
        fm = {"title": title, "type": "paper", "authors": authors, "date": date,
              "journal": journal, "source": source, "doi": doi, "tags": tags,
              "category": "uncat", "summary": summary, "zotero_key": key}
        body = build_body(title, key, journal, date, doi, source, tags, abstract, note)
        out = os.path.join(CONTENT, slug + ".md")
        if os.path.exists(out):
            print("跳过已存在:", slug)
            continue
        write_md(out, fm, body)
        imported += 1
        print("导入:", title[:50])

    print("新增导入 %d 条；重置旧论文 %d 篇。" % (imported, reset_n))
    # 4) 触发构建
    try:
        import build
        build.main()
    except Exception as e:
        print("构建跳过（可稍后运行 build.py）:", e)

def split_tags(s):
    if not s:
        return []
    return [t.strip() for t in s.split(";") if t.strip()]

def build_body(title, key, journal, date, doi, source, tags, abstract, note):
    h = "# %s\n\n" % title
    h += "> 来源：Zotero 导入（Key `%s`）｜期刊：%s｜日期：%s\n" % (key, journal, date)
    if doi:
        h += "> DOI: %s\n" % doi
    if source:
        h += "> URL: %s\n" % source
    if tags:
        h += "> 标签：%s\n" % "、".join(tags)
    h += "\n"
    if abstract:
        h += "## 摘要（Abstract）\n\n%s\n\n" % abstract
    if note:
        h += "## 我的笔记\n\n%s\n\n" % note
    else:
        h += "_（该条目在 Zotero 中暂无关联笔记）_\n\n"
    return h

def write_md(path, fm, body):
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
    open(path, "w", encoding="utf-8").write("---\n" + fm_text + "---\n\n" + body)

if __name__ == "__main__":
    main()
