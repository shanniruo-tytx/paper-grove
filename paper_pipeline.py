#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_pipeline.py — 论文流水线 v3 顶层编排入口

真实链路（LLM 驱动 stage 由 Agent 填充，确定性环节由 paper_pipeline 包负责）：

  INPUT
   ↓ locator        (Agent: 解析 input_url -> identity + source_manifest)
   ↓ identity+dup   (代码: resolve_canonical_id + Duplicate Gate)
   ↓ reader         (Agent: 读论文 -> 抽取 facts)
   ↓ canonical      (代码: 落盘 CanonicalPaper JSON + evidence)
   ↓ deep_renderer  (Agent: Canonical -> 论文拆解.md)
   ↓ plain_renderer (Agent: Canonical -> 论文白话解读.md)
   ↓ semantic_gate  (代码: coverage/numerical/unsupported/alignment/depth)
   ↓ staging        (代码: 阶段性写入 -> 校验 -> 原子 commit / rollback)
   ↓ importer       (代码: 写 content/papers + content/notes, frontmatter 校验)
   ↓ build          (代码: build.py 重建 index)
   ↓ mount_gate     (代码: gate_v2.py 挂载完整性 + 一致性)

支持 --resume RUN_ID：复用上次 run manifest + staging 缓存，REUSED 已 PASS 的上游 stage。

本文件提供 CLI 骨架；LLM stage 的具体实现由 Agent 在会话中调用各 paper-* skill 完成，
再把结果通过 paper_pipeline 包持久化/校验。
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_pipeline import (model, identity, source_manifest, semantic_gate,
                            run_manifest, staging, frontmatter_schema)

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPELINE_VERSION = model.PIPELINE_VERSION


def cmd_dup(args):
    """仅跑身份解析 + 去重检测。"""
    paper_slug = "papers_" + os.path.basename(args.input_url).replace(".md", "")
    paper_path = os.path.join(ROOT, "content", "papers", paper_slug[len("papers_"):] + ".md")
    import re
    fm = {}
    if os.path.exists(paper_path):
        text = open(paper_path, encoding="utf-8").read()
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if m:
            for line in m.group(1).split("\n"):
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
    ident = identity.resolve_identity(fm) if fm else {"title": args.input_url}
    existing = identity.scan_existing_papers(os.path.join(ROOT, "content"))
    res = identity.duplicate_check(ident, existing)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["decision"] in ("NEW", "POSSIBLE_DUPLICATE", "VERSION_UPDATE") else 2


def cmd_smoke(args):
    """对已有论文做只读全链路 Gate（不写 content），产出 canonical/gate_report/source_manifest。"""
    from paper_pipeline.run import smoke_test
    r = smoke_test(args.paper_slug)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


def cmd_resume(args):
    from paper_pipeline.run import resume
    r = resume(args.run_id)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


def main():
    ap = argparse.ArgumentParser(description="paper_pipeline v3")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("dup").add_argument("input_url")
    sub.add_parser("smoke").add_argument("paper_slug")
    sub.add_parser("resume").add_argument("run_id")
    args = ap.parse_args()
    if args.cmd == "dup":
        return cmd_dup(args)
    elif args.cmd == "smoke":
        return cmd_smoke(args)
    elif args.cmd == "resume":
        return cmd_resume(args)
    else:
        ap.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
