#!/usr/bin/env python3
# 重分类：把"论文拆解"与"笔记"匹配回对应论文，无主笔记归为"知识资料"(resource)。
# 默认 dry-run 打印匹配方案；python reclassify.py apply 才真写回。
import os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content")

def parse_fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    body = text[m.end():]
    fm = {}
    for line in m.group(1).split("\n"):
        if not line.strip() or line.lstrip().startswith("- "):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            fm[k] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()] if inner else []
        else:
            fm[k] = v.strip('"').strip("'")
    return fm, body

def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def doi_of(fm, body):
    s = (fm.get("source") or "") + " " + (body or "")
    # 排除半角/全角标点，避免末尾多字符导致匹配失败
    m = re.search(r"10\.\d{4,9}/[^\s\u3000-\u303f\uff00-\uffef\"'<>）)；(；,，]+", s)
    if not m:
        return None
    d = m.group(0).lower()
    if d.startswith("doi.org/"):
        d = d[len("doi.org/"):]
    return d

def note_english_title(body):
    # 兼容多种字段名：论文英文原名 / 原标题 / 英文标题 / 英文题名 / 论文原名 / Title
    m = re.search(r"(?:论文英文原名|原标题|英文标题|英文题名|论文原名|Title)[:：]\s*(.+)", body or "")
    if m:
        return norm(m.group(1).split("\n")[0])
    # 退一步：抓取正文中形如 "# 英文题名" 的行
    m2 = re.search(r"#\s*([A-Z][A-Za-z0-9\s:,()\-]{20,})", body or "")
    if m2:
        return norm(m2.group(1))
    return ""

def note_acronym(title):
    # 取标题开头的连续拉丁词（如 scPower / CellVoyager / MFmamba），长度>=4
    m = re.match(r"^\s*([A-Za-z][A-Za-z0-9_\-]{3,})", (title or "").strip())
    return m.group(1).lower() if m else ""

papers, analyses, notes, others = [], [], [], []
for sub in ("papers", "notes"):
    d = os.path.join(CONTENT, sub)
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md"):
            continue
        p = os.path.join(d, f)
        text = open(p, encoding="utf-8").read()
        fm, body = parse_fm(text)
        slug = os.path.relpath(p, CONTENT)[:-3].replace(os.sep, "_").replace(" ", "_")
        rec = {"file": p, "slug": slug, "fm": fm, "body": body, "text": text,
               "title": fm.get("title") or os.path.splitext(f)[0],
               "ntitle": norm(fm.get("title") or os.path.splitext(f)[0]),
               "doi": doi_of(fm, body)}
        if f.endswith("_论文拆解.md"):
            analyses.append(rec)
        elif fm.get("type") == "note":
            notes.append(rec)
        elif sub == "papers" and fm.get("type", "paper") == "paper":
            papers.append(rec)
        else:
            others.append(rec)

paper_by_doi = {}
for p in papers:
    if p["doi"]:
        paper_by_doi.setdefault(p["doi"], p)

def strip_cjk(s):
    return re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", " ", s or "")

def match_paper(rec):
    # 1) DOI（来源/正文）
    if rec["doi"] and rec["doi"] in paper_by_doi:
        return paper_by_doi[rec["doi"]], "doi"
    body = rec.get("body", "")
    # 候选英文题名：正文"论文英文原名" + 标题去中文后剩余英文（如 "论文拆解：An atlas..."）
    cands = []
    en = note_english_title(body)
    if en:
        cands.append(en)
    cjk_stripped = norm(strip_cjk(rec["title"]))
    if cjk_stripped and cjk_stripped != rec["ntitle"]:
        cands.append(cjk_stripped)
    for cand in cands:
        best, bs = None, 0
        for p in papers:
            b = p["ntitle"]
            if not b:
                continue
            if cand == b:
                return p, "en-title-equal"
            if cand in b or b in cand:
                sc = min(len(cand), len(b))
                if sc > bs:
                    best, bs = p, sc
        if best and bs >= 6:
            return best, "en-title(%d)" % bs
    # 2) 标题开头的拉丁缩写（scPower / CellVoyager / MFmamba ...）
    ac = note_acronym(rec["title"])
    if ac:
        for p in papers:
            hay = (p["ntitle"] + " " + p["slug"]).lower()
            if ac in hay:
                return p, "acronym(%s)" % ac
    # 3) 归一化标题互含（兜底）
    best, bestscore = None, 0
    for p in papers:
        a, b = rec["ntitle"], p["ntitle"]
        if not a or not b:
            continue
        if a == b:
            return p, "title-equal"
        if a in b or b in a:
            score = min(len(a), len(b))
            if score > bestscore:
                best, bestscore = p, score
    return (best, "title-substr(%d)" % bestscore) if (best and bestscore >= 10) else (None, "no-match")

# 明确可确认的映射（笔记标题含某串 -> 论文 slug 含某串）。用于正文无英文题名/DOI 无法自动匹配的情况。
MANUAL = [
    ("视频生成", "Video_Generation_Models"),
    ("生成式递归", "Generative_Recursive_Reasoning"),
    ("用异构分子", "Navigating_chemical-linguistic"),
    ("TPN171H", "TPN171H"),
    ("一种面向单细胞 RNA seq", "agentic_AI_framework"),
    ("基于 90 万", "DNA_repeat_expansions"),
]

def manual_match(rec):
    for nk, pk in MANUAL:
        if nk in rec["title"]:
            for p in papers:
                if pk in p["slug"]:
                    return p
    return None

APPLY = len(sys.argv) > 1 and sys.argv[1] == "apply"

def apply_kind(rec, kind, parent):
    lines = rec["text"].split("\n")
    if any(l.strip().startswith("kind:") for l in lines[:6]):
        return  # 已处理过
    ins = ["kind: " + kind, "parent_paper: " + (parent or "")]
    new = lines[:1] + ins + lines[1:]
    open(rec["file"], "w", encoding="utf-8").write("\n".join(new))

print("=== 论文拆解(analysis) 匹配 ===")
for a in analyses:
    p, why = match_paper(a)
    print("  [%-14s] %-46s -> %s" % (why, a["title"][:46], (p["title"][:46] if p else "（无主）")))
    if APPLY and p:
        apply_kind(a, "analysis", p["slug"])

print("\n=== 笔记(note) 匹配 ===")
n_res = n_att = 0
for n in notes:
    p, why = match_paper(n)
    if not p:
        mp = manual_match(n)
        if mp:
            p, why = mp, "manual"
    if p:
        n_att += 1
        print("  [ATTACH 论文] %-40s -> %s" % (n["title"][:40], p["title"][:46]))
        if APPLY:
            apply_kind(n, "note", p["slug"])
    else:
        n_res += 1
        print("  [RESOURCE ] %s" % n["title"][:64])
        if APPLY:
            apply_kind(n, "resource", "")

print("\n=== 其它(概念卡等) -> resource ===")
for o in others:
    print("  [RESOURCE ] %s  (%s)" % (o["title"][:64], o["file"].split(os.sep)[-2]))
    if APPLY:
        apply_kind(o, "resource", "")

print("\n统计: papers=%d analysis=%d notes=%d others=%d | 笔记挂论文=%d 笔记转资料=%d"
      % (len(papers), len(analyses), len(notes), len(others), n_att, n_res))
if not APPLY:
    print("\n（dry-run 仅打印，未写回。执行 `python reclassify.py apply` 才生效。）")
