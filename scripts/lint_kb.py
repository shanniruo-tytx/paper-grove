#!/usr/env python3
# -*- coding: utf-8 -*-
"""
kb-site 内容契约检查（mechanical gate / 硬闸）。

目的：保证 papers / notes / resources 三套目录各自遵守 kind 契约，
且 resources 绝不混入论文拆解模板——从物理上阻断「文章总结器」两套
harness（论文路线 / 非论文路线）互相串流。

- papers/    -> kind 必须为 paper（或 type:paper）
- notes/     -> kind 必须为 note（或 type:note），且 parent_paper 必须解析到某个 papers slug；
                此外「论文白话解读」笔记（_论文白话解读.md / note_type=paper_explainer）正文必须是
                双栏模板【专业描述】+【白话解释】且带 note_type/pipeline_version；「论文拆解」笔记
                （_论文拆解.md）正文必须是双栏模板【专业描述】+【通俗解释】。缺双栏即视为模型退化成
                单栏纯文本（曾因切换模型后静默通过 build 而出坏笔记），必须拦下。
- resources/ -> kind 必须为 resource，且：
      * 不得写 parent_paper（否则破坏「只在知识库」隔离）
      * category 必须固定 uncat（资源不参与文献库分类树）
      * 正文不得含论文拆解指纹（【专业描述】/【通俗解释】/论文 Story/作者想回答的问题/## #0. 原始论文识别）

返回码：0 = 通过；非 0 = 有违规（build.py 会据此失败，dist 不被 emit）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # kb-site/
CONTENT = os.path.join(ROOT, "content")

# 论文拆解（paper-reader）模板指纹：resources/ 正文里出现任一即视为误用了论文模板
PAPER_FINGERPRINTS = [
    "【专业描述】",
    "【通俗解释】",
    "论文 Story",
    "作者想回答的问题",
    "## #0. 原始论文识别",
]


def parse_fm(text):
    """极简 frontmatter 解析（与 build.py 的兜底逻辑一致，避免引入 yaml 依赖）。"""
    fm, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return fm, text
    body = text[m.end():]
    fm_raw = m.group(1)
    fm = {}
    for line in fm_raw.split("\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            items = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            fm[k] = items
        else:
            fm[k] = v.strip("'\"")
    return fm, body


def rel_of(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def run():
    violations = []
    papers_slugs = set()

    # 先收集 papers slug（与 build.py 的 slug 规则一致：相对 content 的路径，sep/_ 替换，去 .md）
    pd = os.path.join(CONTENT, "papers")
    if os.path.isdir(pd):
        for dp, _, fs in os.walk(pd):
            for f in fs:
                if not f.endswith(".md"):
                    continue
                slug = os.path.relpath(os.path.join(dp, f), CONTENT)[:-3].replace(os.sep, "_").replace(" ", "_")
                papers_slugs.add(slug)

    folders = [
        ("papers", "paper"),
        ("notes", "note"),
        ("resources", "resource"),
    ]
    for folder, expect in folders:
        d = os.path.join(CONTENT, folder)
        if not os.path.isdir(d):
            continue
        for dp, _, fs in os.walk(d):
            for f in sorted(fs):
                if not f.endswith(".md"):
                    continue
                p = os.path.join(dp, f)
                text = open(p, encoding="utf-8").read()
                fm, body = parse_fm(text)
                rel = rel_of(p)
                kind = fm.get("kind") or fm.get("type") or ""

                # 1) kind 契约
                if folder == "papers" and kind != "paper":
                    violations.append("[kind契约] %s : papers/ 下 kind 应为 paper，实际=%r" % (rel, kind))
                if folder == "notes" and kind != "note":
                    violations.append("[kind契约] %s : notes/ 下 kind 应为 note，实际=%r" % (rel, kind))
                if folder == "resources" and kind != "resource":
                    violations.append("[kind契约] %s : resources/ 下 kind 应为 resource，实际=%r" % (rel, kind))

                # 2) resources 额外隔离约束
                if folder == "resources":
                    if fm.get("parent_paper"):
                        violations.append("[隔离] %s : resources 不应有 parent_paper（会破坏「只在知识库」）" % rel)
                    cat = fm.get("category", "uncat")
                    if cat != "uncat":
                        violations.append("[隔离] %s : resources category 应固定 uncat，实际=%r" % (rel, cat))
                    for fp in PAPER_FINGERPRINTS:
                        if fp in body:
                            violations.append("[模板串流] %s : 含论文拆解指纹 %r，resources 不得用 paper-reader 模板" % (rel, fp))
                    # 2.1) resources 必须在 frontmatter 含「一句话概括」字段（标题旁的电梯演讲，硬约束）
                    #      —— 与论文统一：主表格/卡片紧随标题的小字由该字段驱动，与 summary(摘要) 互不影响。
                    if not fm.get("一句话概括"):
                        violations.append("[一句话概括缺失] %s : resources 必须在 frontmatter 含 一句话概括 字段（主表格/卡片紧随标题的小字，硬约束）" % rel)

                # 2.6) 所有论文必须在 frontmatter 含「一句话概括」字段（标题旁的电梯演讲，硬约束）
                #      —— 与旧数据（如 PULSE）统一：一行参数，主表格/卡片/详情均展示；与 summary(摘要) 互不影响。
                if folder == "papers":
                    if not fm.get("一句话概括"):
                        violations.append("[一句话概括缺失] %s : papers 必须在 frontmatter 含 一句话概括 字段（标题旁的电梯演讲，硬约束）" % rel)

                # 3) notes 的 parent_paper（如有）必须解析到某个 papers slug
                #    说明：UI 直接新建的「独立笔记」允许没有 parent_paper（照样在知识库显示），
                #    只有「挂了却挂错」才是不该发生的孤立/断裂，必须拦下。
                if folder == "notes":
                    pp = fm.get("parent_paper") or ""
                    if pp and pp not in papers_slugs:
                        violations.append("[挂载] %s : parent_paper=%r 未匹配任何 papers slug（断裂的挂载）" % (rel, pp))
                    # 3.1) paper_weixin_summary（公众号解读）笔记必须在 frontmatter 含「一句话概括」字段（硬约束）
                    #      —— 与挂载的论文、旧数据统一：标题旁的电梯演讲由该字段驱动，与 summary(摘要) 互不影响。
                    if fm.get("note_type") == "paper_weixin_summary":
                        if not fm.get("一句话概括"):
                            violations.append("[一句话概括缺失] %s : paper_weixin_summary 笔记必须在 frontmatter 含 一句话概括 字段（标题旁的电梯演讲，硬约束）" % rel)

                # 4) notes 正文格式契约（论文路线由 article-summarizer 统一生成）
                #    白话解读：双栏【专业描述】+【白话解释】 + note_type/pipeline_version
                #    论文拆解：双栏【专业描述】+【通俗解释】
                #    漏掉双栏 = 模型退化成单栏纯文本，历史上曾因本闸缺失而静默通过 build。
                if folder == "notes":
                    fname = os.path.basename(p)
                    is_baihua = fname.endswith("_论文白话解读.md") or fm.get("note_type") == "paper_explainer"
                    is_chaijie = fname.endswith("_论文拆解.md")
                    if is_baihua:
                        if fm.get("note_type") != "paper_explainer":
                            violations.append("[白话解读契约] %s : note_type 应为 paper_explainer" % rel)
                        if fm.get("pipeline_version") != "paper-pipeline-v2":
                            violations.append("[白话解读契约] %s : pipeline_version 应为 paper-pipeline-v2" % rel)
                        if "【专业描述】" not in body or "【白话解释】" not in body:
                            violations.append("[白话解读契约] %s : 正文须含双栏标记【专业描述】+【白话解释】（疑似退化成单栏）" % rel)
                    if is_chaijie:
                        if "【专业描述】" not in body or "【通俗解释】" not in body:
                            violations.append("[论文拆解契约] %s : 正文须含双栏标记【专业描述】+【通俗解释】" % rel)

    return violations


def main():
    violations = run()
    if violations:
        print("❌ kb-site 内容契约检查未通过：")
        for v in violations:
            print("  - " + v)
        print("\n共 %d 处违规。请修正后再 build（build 会因本闸失败而终止）。" % len(violations))
        sys.exit(1)
    print("✅ kb-site 内容契约检查通过：papers/notes/resources 的 kind 契约、resources 隔离、防模板串流、一句话概括字段（标题旁电梯演讲，papers/resources/paper_weixin_summary 笔记均强制），以及 notes 正文双栏格式（白话解读【专业描述】+【白话解释】/ 论文拆解【专业描述】+【通俗解释】）均正常。")
    sys.exit(0)


if __name__ == "__main__":
    main()
