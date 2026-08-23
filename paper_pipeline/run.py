#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 论文流水线编排入口（含 Resume）

真实运行模式：
  Agent 负责 LLM 驱动的 stage（locator / reader / canonical / deep_renderer / plain_renderer），
  通过回调/数据对象把结果交给本模块；本模块负责所有确定性环节：
    - 身份解析 + 去重拦截
    - Canonical 落盘 + 来源清单
    - 语义 Gate + 工程 Gate
    - staging 事务导入 + rollback
    - run manifest 记录 + resume

CLI 子命令：
  paper-pipeline/run.py smoke TEST_PAPER_SLUG
      对 content 中已有论文（已有 frontmatter + 双笔记）做"只读"全链路 Gate 验证，
      不修改任何文件，仅生成 gate_report / run_manifest（用于验收与回归）。
  paper-pipeline/run.py resume RUN_ID
      基于上次 run manifest + staging 缓存，重跑失败 stage，REUSED 已 PASS 的上游。
  paper-pipeline/run.py dup INPUT_URL
      仅跑身份解析 + 去重检测（不导入）。

设计原则：本文件不替代 Agent 的 LLM 理解，而是把"可复现、可验证、可恢复"的工程能力落为代码。
"""
from __future__ import annotations
import os, sys, json, argparse, shutil
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from paper_pipeline import (model, identity, source_manifest, semantic_gate,
                            run_manifest, staging, frontmatter_schema)

ALLOWED_CATS = frontmatter_schema.load_allowed_categories(os.path.join(ROOT, "categories.json"))


def _read_note_body(path: str) -> str:
    import re
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    return text[m.end():] if m else text


def _find_note(content_dir: str, paper_slug: str, suffix: str) -> Optional[str]:
    """在 notes 目录找属于该 paper 的笔记（按 paper 简称前缀匹配，避免跨论文误取）。"""
    notes_dir = os.path.join(content_dir, "notes")
    short = paper_slug[len("papers_"):]            # 如 cifm_论文
    short_base = short[:-len("_论文")] if short.endswith("_论文") else short  # 如 cifm
    for fn in os.listdir(notes_dir):
        if fn.endswith(suffix + ".md") and fn.startswith(short_base + "_"):
            return os.path.join(notes_dir, fn)
    return None


def build_canonical_from_paper(paper_slug: str) -> model.CanonicalPaper:
    """从论文 + 双笔记反向抽取一个轻量 Canonical（用于 smoke/回归，真实链路应由 Agent 直接产出）。

    这是"验证用"的降级路径：尽量从笔记中抽取数字/方法名/数据集名，标记 certainty=INFERRED。
    """
    c = model.CanonicalPaper()
    # 从论文 frontmatter 取 identity
    paper_path = os.path.join(ROOT, "content", "papers", paper_slug[len("papers_"):] + ".md")
    if os.path.exists(paper_path):
        import re
        text = open(paper_path, encoding="utf-8").read()
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        fm = {}
        if m:
            for line in m.group(1).split("\n"):
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
        c.identity = identity.resolve_identity(fm)
    deep = _find_note(os.path.join(ROOT, "content"), paper_slug, "_论文拆解")
    plain = _find_note(os.path.join(ROOT, "content"), paper_slug, "_论文白话解读")
    # 抽取方法名/数据集名/数字（简化；真实链路 Agent 应直接产出结构化 Canonical）
    texts = []
    if deep:
        texts.append(_read_note_body(deep))
    if plain:
        texts.append(_read_note_body(plain))
    blob = "\n".join(texts)
    # 数字：覆盖 gate 扫描的同一种指标表述（AUROC/AUC/F1/准确率/Pearson/Spearman + 紧随其后的数值），
    # 以及 p 值。smoke 降级路径从笔记反抽，标记 INFERRED；真实链路由 Agent 直接产出结构化事实。
    import re as _re
    for mm in _re.finditer(r"(AUROC|AUC|F1|准确率|Pearson|Spearman)\s*[:=]?\s*(-?\d+\.\d+)", blob, _re.I):
        c.results.append({"claim": mm.group(1), "value": float(mm.group(2)),
                          "fact_type": model.FACT_TYPE_PAPER, "certainty": model.CERTAIN_INFERRED,
                          "evidence": None})
    for mm in _re.finditer(r"p\s*[<=>]\s*(\d+\.?\d*)", blob, _re.I):
        c.results.append({"claim": "p_value", "value": float(mm.group(1)),
                          "fact_type": model.FACT_TYPE_PAPER, "certainty": model.CERTAIN_INFERRED,
                          "evidence": None})
    for mm in _re.finditer(r"(Pearson|Spearman)\s*[rρ]\s*[=:]?\s*(-?\d+\.\d+)", blob, _re.I):
        c.results.append({"claim": mm.group(1) + "_r", "value": float(mm.group(2)),
                          "fact_type": model.FACT_TYPE_PAPER, "certainty": model.CERTAIN_INFERRED,
                          "evidence": None})
    # 方法名/数据集名（供 alignment 锚点）：仅接受全大写缩写（>=3 字母）或出现在"方法/模型"语境后的专有名词，
    # 避免把论文标题拆成 "Generative/Virtual/Tissue" 之类碎片；排除文献计量/通用缩写。
    BIBLIO_EXCLUDE = {"JCR", "IF", "SCI", "EI", "CNN", "RNN", "GPU", "CPU", "DNA", "RNA",
                      "BIO", "IEEE", "URL", "DOI", "PDF", "HTML", "JSON", "YAML", "API",
                      "FIG", "TAB", "SUP", "ETC", "VS", "AL", "ET", "AL."}
    seen = set()
    for mm in _re.finditer(r"\b([A-Z]{3,}[A-Za-z0-9]*)\b", blob):
        tok = mm.group(1)
        if tok in BIBLIO_EXCLUDE or tok not in seen:
            if tok in BIBLIO_EXCLUDE:
                continue
            seen.add(tok)
            c.methods.append({"name": tok})
    # 从 "方法/模型/框架" 语境附近抽取更可能的方法名（首字母大写短语）
    for mm in _re.finditer(r"(?:方法|模型|框架|网络|算法|架构|module|module\s+\w+)\s*[:：]?\s*[*_]*([A-Z][A-Za-z0-9\-]{2,})", blob):
        tok = mm.group(1)
        if tok not in seen:
            seen.add(tok)
            c.methods.append({"name": tok})
    return c


def smoke_test(paper_slug: str) -> dict:
    """对已有论文做只读全链路 Gate，产出 gate_report + run_manifest，不写 content。"""
    rm = run_manifest.RunManifest(
        run_manifest.make_run_id(paper_slug), paper_slug, "smoke:" + paper_slug, model.PIPELINE_VERSION)
    rm.set_stage("locator", run_manifest.STAGE_REUSED, "smoke 模式复用已有 frontmatter")
    rm.set_stage("reader", run_manifest.STAGE_REUSED, "复用已有双笔记正文")
    rm.set_stage("canonical", run_manifest.STAGE_PASS, "从笔记反向抽取 Canonical（验证用）")

    paper_path = os.path.join(ROOT, "content", "papers", paper_slug[len("papers_"):] + ".md")
    deep = _find_note(os.path.join(ROOT, "content"), paper_slug, "_论文拆解")
    plain = _find_note(os.path.join(ROOT, "content"), paper_slug, "_论文白话解读")
    if not os.path.exists(paper_path):
        rm.add_error("smoke 找不到论文文件")
        rm.finish()
        return {"ok": False, "manifest": rm.to_dict()}

    deep_body = _read_note_body(deep) if deep else ""
    plain_body = _read_note_body(plain) if plain else ""
    # 优先使用已落盘的 hand-authored canonical（权威）；否则降级从笔记反抽（仅回归用，标记非权威）
    canon_path = os.path.join(ROOT, "_papers_archive", paper_slug, "canonical.json")
    if os.path.exists(canon_path):
        c = model.CanonicalPaper.load(canon_path)
        authoritative = True
    else:
        c = build_canonical_from_paper(paper_slug)
        authoritative = False

    # 工程 frontmatter 校验
    perr = frontmatter_schema.validate_file(paper_path, ALLOWED_CATS)
    nerr_d = frontmatter_schema.validate_file(deep, ALLOWED_CATS, paper_slug) if deep else ["深度拆解笔记缺失（可由 gate_v2 挂载 Gate 负责，此处仅告警）"]
    nerr_p = frontmatter_schema.validate_file(plain, ALLOWED_CATS, paper_slug) if plain else ["白话解读笔记缺失（legacy 单笔记或尚未生成，此处仅告警）"]
    # 缺失笔记不算 frontmatter 硬错误（挂载完整性由 gate_v2 负责）
    fm_hard = perr + ([e for e in nerr_d if "缺失" not in e]) + ([e for e in nerr_p if "缺失" not in e])
    fm_ok = not fm_hard
    rm.set_stage("build", run_manifest.STAGE_SKIPPED, "smoke 不重建站点")

    # 语义 Gate（按需降级：缺哪侧就标记哪侧 NOT_APPLICABLE；authoritative 由 canonical 来源决定）
    if deep and plain:
        report = semantic_gate.run_semantic_gate(c, deep_body, plain_body,
                                                 canonical_is_authoritative=authoritative)
        overall = report["overall"]
    elif deep:
        # 仅深度拆解：跑 coverage（deep）+ numerical（仅 deep vs canonical）+ unsupported（deep）
        cov = semantic_gate.coverage_gate(deep_body, semantic_gate.DEEP_REQUIRED, is_plain=False)
        num = semantic_gate.numerical_consistency_gate(c, deep_body, "")
        unsupp = semantic_gate.unsupported_claim_gate(c, deep_body, "")
        # 非权威（反抽 Canonical）：unsupported 仅 WARN
        if not authoritative and unsupp["status"] == semantic_gate.FAIL:
            unsupp = dict(unsupp)
            unsupp["status"] = semantic_gate.PARTIAL
            unsupp["note"] = "Canonical 为反抽降级版，unsupported 仅作 WARN（真实流水线为硬 FAIL）"
        report = {
            "deep_note": {"coverage": cov["overall"], "coverage_details": cov["details"]},
            "plain_note": {k: semantic_gate.NA for k in
                           ["problem_explanation", "motivation", "core_idea", "workflow",
                            "result_explanation", "reasoning", "professional_plain_alignment", "explanation_depth"]},
            "facts": {"numerical_consistency": num["status"], "numerical_details": num,
                      "unsupported_claims": unsupp["status"], "unsupported_details": unsupp},
            "alignment_details": {"status": semantic_gate.NA, "reason": "无白话笔记，跳过对齐"},
            "depth_details": {"overall": semantic_gate.NA, "reason": "无白话笔记，跳过"},
            "overall": semantic_gate.PASS if (cov["overall"] in (semantic_gate.PASS, semantic_gate.PARTIAL)
                                              and num["status"] in (semantic_gate.PASS, semantic_gate.PARTIAL)
                                              and unsupp["status"] in (semantic_gate.PASS, semantic_gate.PARTIAL)) else semantic_gate.FAIL,
        }
        overall = report["overall"]
        rm.add_warning("该论文仅有深度拆解笔记（legacy 单笔记），白话侧 Gate 标记 NOT_APPLICABLE")
    else:
        rm.add_error("既无深度拆解也无白话解读，无法运行语义 Gate")
        report = {"overall": semantic_gate.FAIL, "reason": "无可用笔记"}
        overall = semantic_gate.FAIL

    rm.set_stage("semantic_gate", run_manifest.STAGE_PASS if overall == "PASS" else run_manifest.STAGE_FAIL, overall)
    rm.set_stage("importer", run_manifest.STAGE_SKIPPED, "smoke 不导入")

    # 写报告到 _papers_archive/{slug}/
    out_dir = os.path.join(ROOT, "_papers_archive", paper_slug)
    os.makedirs(out_dir, exist_ok=True)
    gate_path = os.path.join(out_dir, "gate_report.json")
    json.dump(report, open(gate_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    rm.add_output("gate_report", gate_path)
    canonical_out = os.path.join(out_dir, "canonical.json")
    # 不覆盖已存在的 hand-authored canonical（权威）；仅当不存在时才落盘反抽版
    if not os.path.exists(canonical_out):
        c.save(canonical_out)
    rm.add_output("canonical", canonical_out)
    rm.finish()
    return {"ok": fm_ok and report["overall"] == "PASS", "manifest": rm.to_dict(),
            "gate_report": report, "frontmatter_errors": perr + nerr_d + nerr_p}


def dup_check(input_url: str, identity_dict: dict) -> dict:
    existing = identity.scan_existing_papers(os.path.join(ROOT, "content"))
    return identity.duplicate_check(identity_dict, existing)


def resume(run_id: str) -> dict:
    """基于历史 run manifest 恢复：演示 REUSED 上游 stage。

    真实链路中，Agent 应先加载上次 staging 缓存（canonical.json 等），
    对失败 stage 重算，其余标记 REUSED。本函数演示机制。
    """
    run_dir = os.path.join(ROOT, "_runs")
    manifest_path = None
    for fn in os.listdir(run_dir) if os.path.isdir(run_dir) else []:
        if fn == run_id or fn.startswith(run_id):
            cand = os.path.join(run_dir, fn, "manifest.json")
            if os.path.exists(cand):
                manifest_path = cand
                break
    if not manifest_path:
        return {"ok": False, "reason": "未找到 run manifest: " + run_id}
    prev = run_manifest.RunManifest.load(manifest_path)
    new = run_manifest.RunManifest(run_id + "_resume", prev.paper_id, prev.input, model.PIPELINE_VERSION)
    reused, rerun = 0, 0
    for s, info in prev.stages.items():
        if info["status"] in (run_manifest.STAGE_PASS, run_manifest.STAGE_REUSED):
            new.mark_reused(s, "复用上次成功结果（缓存命中）")
            reused += 1
        else:
            new.set_stage(s, run_manifest.STAGE_PENDING, "需重跑")
            rerun += 1
    new.finish()
    return {"ok": True, "reused_stages": reused, "rerun_stages": rerun,
            "manifest": new.to_dict()}


def main():
    ap = argparse.ArgumentParser(description="paper_pipeline 编排")
    sub = ap.add_subparsers(dest="cmd")
    p_smoke = sub.add_parser("smoke")
    p_smoke.add_argument("paper_slug")
    p_dup = sub.add_parser("dup")
    p_dup.add_argument("input_url")
    p_resume = sub.add_parser("resume")
    p_resume.add_argument("run_id")
    args = ap.parse_args()

    if args.cmd == "smoke":
        r = smoke_test(args.paper_slug)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "dup":
        # 演示：用论文 frontmatter 构造 identity（真实链路由 locator 产出）
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
        r = dup_check(args.input_url, ident)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "resume":
        r = resume(args.run_id)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
