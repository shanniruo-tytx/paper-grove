#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入 Zotero RDF 导出到知识库平台。

与 CSV 不同，RDF 保留了完整收藏目录树（z:Collection + dcterms:hasPart 层级）
以及条目与目录的归属、独立笔记（bib:Memo）。本脚本据此：
  1) 重建 categories.json（用户提供的真实分类树；AI 不会自行新增分类）
  2) 导入所有真实条目（journalArticle/book/...，过滤掉 PDF 附件与期刊容器）
     并按其在 RDF 中的归属写入对应 category（未归类的落入 uncat）
  3) 导入独立笔记（Memo）到对应分类
  4) 触发 build.main() 重建 dist/

约束：AI 不会在“未来解析新文章”时新建分类；本脚本仅在“用户显式提供 RDF 树”时
      一次性重建整棵树，符合“你按照这个做好分类树 / 我不能自行修改”的约定。
"""
import os, re, sys, json, html
import xml.etree.ElementTree as ET
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content", "papers")
NOTES = os.path.join(ROOT, "content", "notes")
CATFILE = os.path.join(ROOT, "categories.json")
RDF_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "PhD文献.rdf")

# RDF 命名空间在 parse_rdf() 内从解析出的 root.tag 动态提取（见下方 global RDF），
# 不在此硬编码，避免字面量被异常字符污染导致属性键匹配失败。
# 注意：ElementTree 的属性键形如 "{uri}about"，必须带花括号。
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"

os.makedirs(CONTENT, exist_ok=True)
os.makedirs(NOTES, exist_ok=True)


def local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def res_of(el):
    return el.get(RDF + "resource")


def child(el, name):
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def child_text(el, name):
    c = child(el, name)
    return (c.text or "").strip() if c is not None else ""


def html2md(h):
    if not h:
        return ""
    h = re.sub(r"(?i)<h1[^>]*>", "\n# ", h)
    h = re.sub(r"(?i)<h2[^>]*>", "\n## ", h)
    h = re.sub(r"(?i)<h3[^>]*>", "\n### ", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"(?i)</?(p|div|br|ul|ol|blockquote)[^>]*>", "\n", h)
    h = re.sub(r"(?i)<a[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", r"\2 (\1)", h)
    h = re.sub(r"(?i)<b[^>]*>(.*?)</b>", r"**\1**", h)
    h = re.sub(r"(?i)<i[^>]*>(.*?)</i>", r"*\1*", h)
    h = re.sub(r"(?i)<[^>]+>", "", h)
    h = h.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    h = re.sub(r"\n{3,}", "\n\n", h).strip()
    return h


def slugify(s, maxlen=60):
    s = re.sub(r"[^\w一-鿿\-]+", "_", s).strip("_")
    return s[:maxlen] or "item"


# 真实条目类型（排除 attachment / 容器 / 笔记）
SKIP_TYPES = {"attachment", "note"}
REAL_TYPES = {
    "journalarticle", "book", "booksection", "conferencepaper", "report",
    "thesis", "webpage", "magazinearticle", "newspaperarticle", "preprint",
    "manuscript", "letter", "document", "presentation", "standard", "patent",
    "computerprogram", "blogpost", "podcast", "interview", "forumpost",
    "encyclopediaarticle", "map", "bill", "case", "film", "audiovisual", "email",
    "encyclopedia article",
}


def parse_rdf(path):
    tree = ET.parse(path)
    root = tree.getroot()
    # 从 root.tag 动态提取 rdf 命名空间，避免硬编码字面量被异常字符污染
    global RDF
    _m = re.match(r"^\{(.+)\}RDF$", root.tag)
    if _m:
        RDF = "{" + _m.group(1) + "}"

    collections = {}   # about -> {title, sub:[], items:[]}
    items = {}         # about -> element (real + containers + attachments)
    memos = {}         # about -> element (notes)
    containers = {}    # about(urn:issn) -> title

    for el in root.iter():
        about = el.get(RDF + "about")
        if not about:
            continue
        ln = local(el.tag)
        if ln == "Collection":
            collections[about] = {
                "title": child_text(el, "title"),
                "sub": [res_of(c) for c in el if local(c.tag) == "hasPart" and (res_of(c) or "").startswith("#collection_")],
                "items": [res_of(c) for c in el if local(c.tag) == "hasPart" and res_of(c) and not res_of(c).startswith("#collection_")],
            }
        elif ln == "Memo":
            memos[about] = el
        else:
            it = child_text(el, "itemType").lower()
            if it == "note":
                memos[about] = el
            else:
                items[about] = el
                if about.startswith("urn:") and not it:
                    containers[about] = child_text(el, "title")

    return collections, items, memos, containers


def build_categories(collections):
    # parent map
    parent = {}
    for about, info in collections.items():
        for s in info["sub"]:
            parent[s] = about
    cats = []
    for about, info in collections.items():
        cid = about[1:]  # strip leading '#'
        p = parent.get(about)
        cats.append({
            "id": cid,
            "name": info["title"] or cid,
            "parent": (p[1:] if p else None),
        })
    # 兜底：保留 uncat
    if not any(c["id"] == "uncat" for c in cats):
        cats.append({"id": "uncat", "name": "待归类", "parent": None})
    return cats, parent


def depth(cid, parent_map, coll_by_id):
    d = 0
    cur = cid
    seen = set()
    while cur and cur in parent_map and cur not in seen:
        seen.add(cur)
        cur = parent_map[cur][1:]  # parent about -> id
        d += 1
    return d


def extract_authors(el):
    # bib:authors > rdf:Seq > rdf:li > foaf:Person
    out = []
    aroot = child(el, "authors")
    if aroot is not None:
        for seq in aroot:
            if local(seq.tag) != "Seq":
                continue
            for li in seq:
                if local(li.tag) != "li":
                    continue
                for person in li:
                    if local(person.tag) != "Person":
                        continue
                    sn = child_text(person, "surname")
                    gn = child_text(person, "givenName")
                    if sn or gn:
                        out.append((" ".join([gn, sn]).strip() if gn else sn))
    return out


def extract_doi(el):
    for c in el:
        ln = local(c.tag)
        if ln == "identifier":
            t = (c.text or "").strip()
            if t.lower().startswith("doi "):
                return t[4:].strip()
            if re.match(r"^10\.\d{4,9}/", t):
                return t
        if ln == "doi":
            t = (c.text or "").strip()
            if t:
                return t
    return ""


def extract_tags(el):
    tags = []
    for c in el:
        ln = local(c.tag)
        if ln in ("subject", "AutomaticTag"):
            t = (c.text or "").strip()
            if t:
                tags.append(t)
    return tags


def main():
    collections, items, memos, containers = parse_rdf(RDF_PATH)
    cats, parent = build_categories(collections)
    coll_by_id = {c["id"]: c for c in cats}
    parent_map = {c["id"]: c["parent"] for c in cats if c["parent"]}

    # 写入 categories.json
    json.dump(cats, open(CATFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("分类树已写入：%d 个分类（含 uncat）" % len(cats))

    # 条目 -> 所属 collection（about 列表）
    item2col = {}
    for about, info in collections.items():
        for it in info["items"]:
            item2col.setdefault(it, []).append(about[1:])  # id

    def pick_cat(about):
        cols = item2col.get(about)
        if not cols:
            return "uncat"
        # 取最深（层级最多）的分类
        cols.sort(key=lambda c: depth(c, parent_map, coll_by_id), reverse=True)
        return cols[0]

    # memo -> 父条目（通过 item 的 hasPart 指向 memo）
    note2item = {}
    for about, el in items.items():
        it = child_text(el, "itemType").lower()
        if it in SKIP_TYPES or about.startswith("urn:"):
            continue
        for c in el:
            if local(c.tag) == "hasPart":
                r = res_of(c)
                if r in memos:
                    note2item.setdefault(r, about)
    # memo -> 父 collection（通过 collection 的 items 列出 memo）
    note2col = {}
    for about, info in collections.items():
        for it in info["items"]:
            if it in memos:
                note2col.setdefault(it, about[1:])

    # ---- 清理旧的 zotero_* 自动导入，避免重复 ----
    removed = 0
    for d in (CONTENT, NOTES):
        for f in os.listdir(d):
            if f.startswith("zotero_") and f.endswith(".md"):
                os.remove(os.path.join(d, f))
                removed += 1
    print("清理旧的 zotero_* 导入文件：%d 个" % removed)

    # ---- 导入笔记（Memo）----
    note_imported = 0
    for about, el in memos.items():
        val = child(el, "value")
        body = html2md(val.text if val is not None else "")
        if not body:
            continue
        # 归属：优先挂在文章，否则挂分类，否则 uncat
        if about in note2item:
            # 笔记作为“我的笔记”并入对应文章（在文章导入处处理），此处跳过独立写入
            continue
        cat = note2col.get(about, "uncat")
        first_line = re.sub(r"[#*\-\s]+", " ", body.splitlines()[0] if body.splitlines() else "").strip()
        title = (first_line[:50] or "笔记")
        fm = {"title": title, "type": "note", "category": cat,
              "tags": [], "date": "", "zotero_uri": about}
        slug = "zotero_note_%s" % slugify(title + about[-8:])
        out = os.path.join(NOTES, slug + ".md")
        write_md(out, fm, "# %s\n\n%s" % (title, body))
        note_imported += 1
    print("导入独立笔记：%d 条" % note_imported)

    # ---- 导入真实条目 ----
    paper_imported = 0
    for about, el in items.items():
        it = child_text(el, "itemType").lower()
        if it in SKIP_TYPES:
            continue
        if about.startswith("urn:"):
            continue  # 期刊/容器
        title = child_text(el, "title")
        if not title:
            continue
        authors = extract_authors(el)
        date = child_text(el, "date")[:10]
        doi = extract_doi(el)
        abstract = child_text(el, "abstract")
        journal = ""
        iso = child(el, "isPartOf")
        if iso is not None:
            r = res_of(iso)
            journal = containers.get(r, "")
        tags = extract_tags(el)
        url = about if about.lower().startswith("http") else ""
        if not url and doi:
            url = "https://doi.org/" + doi
        cat = pick_cat(about)
        # 该条目是否挂有笔记
        note_body = ""
        for mabout, pabout in note2item.items():
            if pabout == about:
                v = child(memos[mabout], "value")
                note_body = html2md(v.text if v is not None else "")
        summary = abstract[:240].replace("\n", " ")
        slug = "zotero_%s_%s" % (slugify(about[-12:]), slugify(title))
        fm = {
            "title": title, "type": "paper", "authors": authors, "date": date,
            "journal": journal, "source": url, "doi": doi, "tags": tags,
            "category": cat, "summary": summary, "zotero_uri": about,
            "item_type": child_text(el, "itemType"),
        }
        body = build_body(title, journal, date, doi, url, tags, abstract, note_body)
        out = os.path.join(CONTENT, slug + ".md")
        write_md(out, fm, body)
        paper_imported += 1
        if paper_imported <= 5 or paper_imported % 50 == 0:
            print("  导入[%s] %s" % (cat, title[:50]))

    print("导入真实条目：%d 篇" % paper_imported)

    # ---- 重建 ----
    try:
        import build
        build.main()
        print("已触发 build.main() 重建 dist/")
    except Exception as e:
        print("构建跳过：", e)


def build_body(title, journal, date, doi, source, tags, abstract, note):
    h = "# %s\n\n" % title
    meta = []
    if journal:
        meta.append("期刊：%s" % journal)
    if date:
        meta.append("日期：%s" % date)
    if doi:
        meta.append("DOI：%s" % doi)
    if source:
        meta.append("URL：%s" % source)
    if meta:
        h += "> " + "｜".join(meta) + "\n\n"
    if tags:
        h += "> 标签：" + "、".join(tags) + "\n\n"
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
