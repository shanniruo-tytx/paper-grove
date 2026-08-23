import os, re, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = ROOT  # root md files
DST = os.path.join(ROOT, "kb-site", "content", "papers")
os.makedirs(DST, exist_ok=True)

# known date / tags overrides (keyed by filename without ext)
DATE = {
    "CellDecoder_论文拆解": "2025-10-20",
    "Self-Harness_论文拆解": "2026-06-08",
    "VL-JEPA_论文拆解": "2026-02-02",
    "AlignIF_论文拆解": "2026-07-30",
    "Stroke_gammaDeltaT_论文拆解": "2026-04-09",
    "scTranslation_论文拆解": "2026-06-09",
    "scAgeClock_论文拆解": "2026-07-01",
    "MFmamba_论文拆解": "2026-01-01",
    "PRDX4_BreastBoneMeta_论文拆解": "2026-01-01",
    "EpiAwareNet_论文拆解": "2026-06-01",
    "Science_AD_3Dgenome_拆解": "2026-07-01",
}
TAGS = {
    "Science_AD_3Dgenome_拆解": ["single-cell", "3D-genome", "Alzheimer", "multi-omics"],
    "Self-Harness_论文拆解": ["agent", "LLM", "self-improvement", "benchmark"],
    "MFmamba_论文拆解": ["CV", "remote-sensing", "Mamba", "super-resolution"],
    "VL-JEPA_论文拆解": ["CV", "multimodal", "JEPA", "vision-language"],
    "AlignIF_论文拆解": ["RNA-design", "AI4Science", "deep-learning", "generative"],
    "Stroke_gammaDeltaT_论文拆解": ["immunology", "single-cell", "stroke", "T-cells"],
    "scTranslation_论文拆解": ["single-cell", "benchmark", "multi-omics", "translation"],
    "CellDecoder_论文拆解": ["single-cell", "deep-learning", "cell-annotation", "XAI"],
    "PRDX4_BreastBoneMeta_论文拆解": ["multi-omics", "ML", "breast-cancer", "metastasis"],
    "scAgeClock_论文拆解": ["single-cell", "aging", "deep-learning", "clock"],
    "EpiAwareNet_论文拆解": ["single-cell", "GRN", "transformer", "multi-omic"],
}

def grab(body, label):
    m = re.search(r"-\s*\*\*%s\*\*[：:]\s*(.+)" % label, body)
    return m.group(1).strip() if m else ""

def first_line_summary(body):
    # strip the metadata block, take first non-empty plain line as summary
    for ln in body.splitlines():
        s = ln.strip()
        if s and not s.startswith("#") and not s.startswith("-") and not s.startswith(">") and not s.startswith("*"):
            return s[:220]
    return ""

moved = 0
for f in sorted(os.listdir(SRC)):
    if not f.endswith("论文拆解.md"):
        continue
    base = f[:-3]
    text = open(os.path.join(SRC, f), encoding="utf-8").read()
    title = grab(text, "论文英文原名") or base
    journal = grab(text, "期刊名称") or ""
    year = (grab(text, "发表年份") or "")[:4]
    source = grab(text, "论文原文链接") or ""
    source = source.split("（")[0].strip()
    date = DATE.get(base, (year + "-01-01") if year else "2026-01-01")
    tags = TAGS.get(base, [])
    summary = first_line_summary(text)
    fm = [
        "---",
        "title: " + title,
        "type: paper",
        "category: 待归类",
        "journal: " + journal,
        "date: " + date,
        "source: " + source,
        "tags: [" + ", ".join(tags) + "]",
        "summary: " + (summary.replace('"', "'") if summary else ""),
        "---",
        "",
    ]
    out = os.path.join(DST, base + ".md")
    with open(out, "w", encoding="utf-8") as w:
        w.write("\n".join(fm) + "\n" + text)
    archive = os.path.join(SRC, "_papers_archive")
    os.makedirs(archive, exist_ok=True)
    shutil.move(os.path.join(SRC, f), os.path.join(archive, f))  # original kept as backup
    moved += 1
    print("moved:", base, "|", title[:50])

print("total moved:", moved)
