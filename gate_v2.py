#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_v2.py — kb-site 论文流水线 v2 挂载完整性 + 一致性格查 Gate

检查范围：
  A. MOUNT GATE（挂载完整性）
     - BUILD_INDEX_PRESENT
     - NO_ORPHAN_NOTE（兼容既有未命名手动笔记，仅告警）
     - 对 pipeline_version == paper-pipeline-v2 的论文：
         DEEP_ANALYSIS_PRESENT      存在 论文拆解 附属笔记
         PLAIN_EXPLANATION_PRESENT  存在 论文白话解读 附属笔记
         PARENT_PAPER_MATCH         两笔记 parent_paper 相等且 == 论文 slug
         FRONTMATTER_VALID          两笔记 frontmatter 合法
  B. CONSISTENCY GATE（双笔记事实一致性）
     - 抽取两笔记中的关键指标数值（Pearson/Spearman r、p 值、F1、准确率、AUC…）
       同名指标数值集合必须一致，否则 FAIL

legacy 论文（无 pipeline_version 或单笔记）不强制双笔记，仅检查无孤儿。

退出码：发现任何 v2 论文 Gate 失败 -> 1；否则 0。
"""
import os, re, json, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "dist", "index.json")
CONTENT = os.path.join(ROOT, "content")

# 指标词 -> 正则（捕获数值，允许百分位）
INDICATORS = {
    "Pearson_r": r"[Pp]earson\s*[rρ]\s*[=:]?\s*([-+]?\d+\.\d+)",
    "Spearman_rho": r"[Ss]pearman\s*ρ?\s*[=:]?\s*([-+]?\d+\.\d+)",
    "p_value_lt": r"p\s*[<≤]\s*(\d+\.?\d*)",
    "p_value_eq": r"p\s*[=:]\s*(\d+\.\d+)",
    "F1": r"[Ff]1[=-]?\s*(\d+\.?\d+)",
    "accuracy": r"准确率\s*[=:]?\s*(\d+\.?\d+%?)",
    "AUC": r"[Aa][Uu][Cc]\s*[=:]?\s*(\d+\.\d+)",
    "micro_F1": r"micro-?[Ff]1\s*[=:]?\s*(\d+\.\d+)",
    "macro_F1": r"macro-?[Ff]1\s*[=:]?\s*(\d+\.\d+)",
}

def parse_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None, text
    fm_raw = m.group(1)
    fm = {}
    for line in fm_raw.split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, text[m.end():]

def extract_indicators(text):
    """返回 {indicator: set(values)}"""
    out = {}
    for name, pat in INDICATORS.items():
        vals = re.findall(pat, text)
        if vals:
            out[name] = set(vals)
    return out

def main():
    if not os.path.exists(INDEX):
        print("FAIL BUILD_INDEX_PRESENT: dist/index.json 不存在，请先 build.py")
        sys.exit(1)
    d = json.load(open(INDEX, encoding="utf-8"))
    ents = d["entries"]
    papers = [e for e in ents if e["kind"] == "paper"]
    notes = [e for e in ents if e["kind"] == "note"]

    print("=" * 64)
    print("MOUNT GATE")
    print("=" * 64)
    overall_ok = True

    # 孤儿笔记（排除已知既有未命名手动笔记：slug 以 notes_ 开头且无 parent 或 parent 空）
    orphans = [n for n in notes if not n.get("parent_paper")]
    if orphans:
        print("WARN NO_ORPHAN_NOTE: 以下笔记无 parent_paper（兼容既有手动笔记，仅告警）:")
        for o in orphans:
            print("   -", o["slug"])
    else:
        print("PASS NO_ORPHAN_NOTE")

    # 重新读取笔记源文件 frontmatter（index 不含 note_type，但含 kind/parent_paper）
    # 建立 slug -> 源文件 frontmatter + 正文
    note_src = {}
    for n in notes:
        # 源文件：index 的 path 是构建产物 .html；真实源是 content/ 下某 .md，文件名 = slug 去 notes_ 前缀
        fname = n["slug"]
        if fname.startswith("notes_"):
            fname = fname[len("notes_"):]
        target = fname + ".md"
        src = None
        for dp, _, fs in os.walk(CONTENT):
            if target in fs:
                src = os.path.join(dp, target)
                break
        if not src:
            continue
        text = open(src, encoding="utf-8").read()
        fm, body = parse_frontmatter(text)
        note_src[n["slug"]] = {"fm": fm or {}, "body": body, "raw": text}

    for p in papers:
        slug = p["slug"]
        # 论文源文件：slug 形如 papers_cifm_论文（papers 子目录 + 文件名）
        # 用 os.walk 稳健查找：文件名 == slug + .md 即匹配（slug 已含 papers_ 前缀）
        paper_path = None
        # 文件名不含 papers_ 前缀：slug = papers_{简称}_论文，文件 = {简称}_论文.md
        fname = slug
        if fname.startswith("papers_"):
            fname = fname[len("papers_"):]
        target = fname + ".md"
        for dp, _, fs in os.walk(CONTENT):
            if target in fs:
                paper_path = os.path.join(dp, target)
                break
        paper_fm = {}
        if os.path.exists(paper_path):
            paper_fm = parse_frontmatter(open(paper_path, encoding="utf-8").read())[0] or {}
        # 若论文条目本身 index 里有 pipeline_version 也采纳（双保险）
            is_v2 = (paper_fm.get("pipeline_version") == "paper-pipeline-v2") or (p.get("pipeline_version") == "paper-pipeline-v2")

        atts = [n for n in notes if n.get("parent_paper") == slug]
        deep = [n for n in atts if (note_src.get(n["slug"], {}).get("fm", {}).get("note_type") == "paper_analysis"
                                    or "论文拆解" in n["slug"] or n["slug"].endswith("_论文拆解"))]
        plain = [n for n in atts if (note_src.get(n["slug"], {}).get("fm", {}).get("note_type") == "paper_explainer"
                                     or "论文白话解读" in n["slug"] or n["slug"].endswith("_论文白话解读"))]

        if not is_v2:
            # legacy：仅检查 parent 存在
            if atts:
                print("LEGACY %s -> %d 附属笔记（不强制双笔记）" % (slug, len(atts)))
        else:
            print("-" * 64)
            print("V2 %s" % slug)
            ok = True
            # DEEP
            if deep:
                print("  PASS DEEP_ANALYSIS_PRESENT (%s)" % deep[0]["slug"])
            else:
                print("  FAIL DEEP_ANALYSIS_PRESENT: 缺论文拆解笔记")
                ok = False
            # PLAIN
            if plain:
                print("  PASS PLAIN_EXPLANATION_PRESENT (%s)" % plain[0]["slug"])
            else:
                print("  FAIL PLAIN_EXPLANATION_PRESENT: 缺论文白话解读笔记")
                ok = False
            # PARENT MATCH
            parents = set(n.get("parent_paper") for n in (deep + plain))
            if parents == {slug}:
                print("  PASS PARENT_PAPER_MATCH")
            else:
                print("  FAIL PARENT_PAPER_MATCH: parents=%s" % parents)
                ok = False
            # FRONTMATTER VALID
            fmv_ok = True
            for n in (deep + plain):
                raw = note_src.get(n["slug"], {}).get("raw", "")
                if not re.match(r"^---\s*\n.*?\n---\s*\n", raw, re.DOTALL):
                    print("  FAIL FRONTMATTER_VALID: %s 缺闭合 ---" % n["slug"])
                    fmv_ok = False
            if fmv_ok:
                print("  PASS FRONTMATTER_VALID")
            ok = ok and fmv_ok

            # CONSISTENCY GATE
            if deep and plain:
                dtxt = note_src.get(deep[0]["slug"], {}).get("body", "")
                ptxt = note_src.get(plain[0]["slug"], {}).get("body", "")
                di = extract_indicators(dtxt)
                pi = extract_indicators(ptxt)
                confl = []
                for name in set(di) | set(pi):
                    dv = di.get(name, set())
                    pv_ = pi.get(name, set())
                    if dv and pv_ and dv != pv_:
                        confl.append((name, dv, pv_))
                if confl:
                    print("  FAIL CONSISTENCY_GATE: 关键指标数值冲突 ->")
                    for name, dv, pv_ in confl:
                        print("     %s: 拆解=%s 白话=%s" % (name, dv, pv_))
                    ok = False
                else:
                    print("  PASS CONSISTENCY_GATE（关键指标数值一致或无冲突）")
                    if di or pi:
                        print("     抽取指标: 拆解=%s | 白话=%s" % (di, pi))
            if ok:
                print("  >>> V2 GATE: PASS")
            else:
                print("  >>> V2 GATE: FAIL")
                overall_ok = False

    print("=" * 64)
    if overall_ok:
        print("ALL V2 GATES PASSED")
        sys.exit(0)
    else:
        print("SOME V2 GATES FAILED — 请回到原文核对修正")
        sys.exit(1)

if __name__ == "__main__":
    main()
