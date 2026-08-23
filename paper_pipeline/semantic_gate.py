#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semantic_gate.py — 语义质量 Gate (Semantic Quality Gate)

与 gate_v2.py（工程挂载 + 数值一致性）互补。本 Gate 评价"内容写得好不好"，
不依赖字数，而是检查：问题有没有被回答、关键事实是否覆盖、重要数字是否一致、
是否有无依据宣称、专业↔白话是否对齐、核心技术是否真被解释。

设计为：deterministic checks 为主 + 轻量结构化字段校验，避免无限 Agent 互审。
对真正需要语义理解处（专业↔白话对齐、解释深度），使用可解释的启发式 + 可选 LLM hook。

输出 machine-readable gate_report，每项带 status 与 reason，便于后续 targeted repair。
"""
from __future__ import annotations
import json, re, os
from typing import Any, Dict, List, Optional, Tuple

PASS, PARTIAL, FAIL, NA = "PASS", "PARTIAL", "FAIL", "NOT_APPLICABLE"


def _extract_numbers(text: str) -> List[Tuple[str, float]]:
    """抽取文本中所有浮点数（含百分比），返回 (原始串, 数值)。"""
    out = []
    for m in re.finditer(r"(-?\d+\.\d+%?|-?\d+%?)", text):
        raw = m.group(1)
        num = float(raw.rstrip("%"))
        out.append((raw, num))
    return out


def _num_tokens(text: str) -> set:
    """用于数字一致性比较：从文本提取"数值集合"（归一化到 float）。"""
    return {round(v, 4) for _, v in _extract_numbers(text)}


# ---------------------------------------------------------------------------
# 1. Coverage Gate
# ---------------------------------------------------------------------------

# 深度拆解要求较高事实覆盖（属于 Deep Analysis Renderer）
DEEP_REQUIRED = ["problem", "method", "datasets", "experiments", "results", "innovation", "limitations"]
# 白话解读（Quick Understanding Renderer）只要求讲清五件事，不做完整 coverage
PLAIN_REQUIRED = ["problem", "motivation", "core_idea", "workflow", "result", "reasoning"]

# 白话笔记字数上限（中文字符）。超出视为"写成第二篇完整拆解"，FAIL。
# 双栏速读（专业描述+白话解释+术语表）默认约 1200~2200 中文字，给到 2600 余量避免误伤。
QUICK_READ_MAX_HAN = 2600
# 白话笔记最短保障（避免空话敷衍），低于此值仅 WARN 不 FAIL。
QUICK_READ_MIN_HAN = 700

# 白话笔记不应复刻深度拆解的 #0~#9 长模板结构（注意：【专业描述】/【白话解释】是白话解读 Renderer 的正确双栏格式，不再视为违禁）
DEEP_TEMPLATE_FORBIDDEN = ["#0", "#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8", "#9"]


def _has_meaningful(text: str, keywords: List[str], min_hits: int = 1) -> bool:
    """deterministic 检查：文本是否包含给定语义关键词簇（至少一个簇命中）。"""
    if not text:
        return False
    t = text.lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in t:
            hits += 1
    return hits >= min_hits


PROBLEM_KW = ["问题", "挑战", "不足", "缺乏", "难以", "瓶颈", "gap", "problem", "challenge",
               "不等于", "解释不了", "不足以", "无法解释", "缺口", "饱和"]
METHOD_KW = ["方法", "模型", "框架", "网络", "算法", "架构", "method", "model", "framework", "network", "architecture"]
DATA_KW = ["数据", "数据集", "样本", "细胞", "dataset", "data", "sample", "cohort", "benchmark"]
EXP_KW = ["实验", "验证", "评估", "基准", "experiment", "evaluation", "benchmark", "validation"]
RESULT_KW = ["结果", "指标", "准确率", "AUC", "AUROC", "F1", "performance", "result", "metric", "accuracy"]
INNO_KW = ["创新", "首次", "新颖", "novel", "innovation", "first", "贡献", "亮点",
            "与前作", "区别", "不同于", "突破性", "开创", "提出", "核心贡献", "价值在于"]
LIMIT_KW = ["局限", "限制", "不足", "未来", "limitation", "future", "caveat"]
MOTIV_KW = ["为什么", "意义", "重要", "需求", "动机", "why", "motivation", "significance"]
IDEA_KW = ["核心想法", "核心思想", "关键思路", "idea", "核心", "intuition"]
WORKFLOW_KW = ["输入", "步骤", "流程", "输出", "input", "step", "pipeline", "output", "workflow",
                "先用", "再用", "最后", "演进", "路线", "先", "随后", "阶段"]
REASON_KW = ["为什么有效", "机制", "原因", "有效", "mechanism", "why it works",
             "边界", "短板", "现阶段", "关键", "不足", "局限", "但必须", "然而", "并不是"]


def coverage_gate(text: str, required: List[str], is_plain: bool) -> Dict[str, Any]:
    checks = {
        "problem": (PROBLEM_KW, 1),
        "method": (METHOD_KW, 1),
        "datasets": (DATA_KW, 1),
        "experiments": (EXP_KW, 1),
        "results": (RESULT_KW, 1),
        "innovation": (INNO_KW, 1),
        "limitations": (LIMIT_KW, 1),
        "motivation": (MOTIV_KW, 1),
        "core_idea": (IDEA_KW, 1),
        "workflow": (WORKFLOW_KW, 1),
        "reasoning": (REASON_KW, 1),
    }
    report = {}
    overall = PASS
    for key in required:
        kws, min_hits = checks.get(key, ([], 1))
        ok = _has_meaningful(text, kws, min_hits)
        status = PASS if ok else (NA if key not in checks else FAIL)
        if status == FAIL:
            overall = FAIL
        report[key] = {
            "status": status,
            "reason": "文本包含该主题关键词簇" if ok else f"文本未检测到足够 '{key}' 相关表述（需覆盖该主题）",
        }
    return {"overall": overall, "details": report}


# ---------------------------------------------------------------------------
# 2. Numerical Consistency Gate (Canonical vs Deep vs Plain)
# ---------------------------------------------------------------------------

def _num_equal_scale(a: float, b: float, tol: float = 0.01) -> bool:
    """容忍百分比(×100)、万(×1e4)、亿(×1e8) 量级差异的数值相等比较。

    tol=0.01（绝对 1%）用以捕获明显转录错误（如 0.913→0.931，差 1.97%）；
    同时允许 %/万/亿 量级换算。量级换算用较宽容差，数值本身用严容差。
    """
    if a == b:
        return True
    # 数值本身严格比较（绝对 1% 或相对 0.5%，取宽松者）
    if abs(a - b) <= max(0.01, abs(a) * 0.005):
        return True
    # 量级换算比较（较宽，仅用于 %/万/亿）
    for scale in (100.0, 1e4, 1e8):
        if abs(a - b * scale) <= max(0.01, abs(a) * 0.005):
            return True
        if abs(a * scale - b) <= max(0.01, abs(b) * 0.005):
            return True
    return False


def numerical_consistency_gate(canonical: Any, deep_text: str, plain_text: str) -> Dict[str, Any]:
    """关键数字必须：canonical == deep == plain（容忍 %/万/亿 量级）。任一不一致 -> FAIL 并标出。"""
    mismatches = []
    # 从 canonical results 取数值（含 unit 用于百分比归一化）
    canon_vals = []
    for r in getattr(canonical, "results", []) or []:
        v = r.get("value") if isinstance(r, dict) else getattr(r, "value", None)
        claim = r.get("claim") if isinstance(r, dict) else getattr(r, "claim", None)
        unit = (r.get("unit") if isinstance(r, dict) else getattr(r, "unit", None)) or ""
        if isinstance(v, (int, float)):
            cv = float(v) * 100.0 if "%" in str(unit) else float(v)
            canon_vals.append((claim or "result", cv))
    # 从 canonical data sample_size 取
    for d in getattr(canonical, "data", []) or []:
        ss = d.get("sample_size") if isinstance(d, dict) else getattr(d, "sample_size", None)
        name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
        if isinstance(ss, (int, float)):
            canon_vals.append(("%s.sample_size" % (name or "data"), float(ss)))

    deep_nums = _num_tokens(deep_text)
    plain_nums = _num_tokens(plain_text)

    for label, cval in canon_vals:
        # 深度拆解：强制覆盖（Deep Analysis 必须完整呈现关键数字）
        if deep_nums and not any(_num_equal_scale(cval, n) for n in deep_nums):
            close = [n for n in deep_nums if abs(n - cval) / max(abs(cval), 1e-9) < 0.5 and n != cval]
            mismatches.append({
                "location": "deep", "label": label, "canonical_value": cval,
                "note_value": sorted(close)[0] if close else "缺失",
                "reason": f"Canonical {label}={cval} 未在深度拆解关键数字中找到对应值"
                          + (f"；笔记出现相近数值 {sorted(close)[0]}" if close else "；笔记可能遗漏或改写错误"),
            })
        # 白话解读：不强制全覆盖（速读笔记只选关键结果）。
        # 仅当同一 canonical 数字在 deep 一致、在 plain 也出现但不一致时才报矛盾；
        # plain 单独缺失某数字不计入 FAIL（完整 result coverage 属于 Deep Analysis）。
        if plain_nums and any(_num_equal_scale(cval, n) for n in plain_nums):
            # plain 出现了该 canonical 数字，验证 deep 侧也一致（防两边互相矛盾）
            if deep_nums and not any(_num_equal_scale(cval, n) for n in deep_nums):
                close = [n for n in deep_nums if abs(n - cval) / max(abs(cval), 1e-9) < 0.5 and n != cval]
                mismatches.append({
                    "location": "plain", "label": label, "canonical_value": cval,
                    "note_value": sorted(close)[0] if close else "缺失",
                    "reason": f"白话解读出现 Canonical {label}={cval}，但深度拆解侧数值不一致（两边矛盾）",
                })

    status = FAIL if mismatches else PASS
    return {
        "status": status,
        "canonical_numbers": [c[1] for c in canon_vals],
        "mismatches": mismatches,
        "reason": "关键数字与 Canonical 一致（容忍 %/万/亿 量级）" if status == PASS
                  else "发现关键数字与 Canonical 不一致",
    }


# ---------------------------------------------------------------------------
# 3. Unsupported Claim Gate
# ---------------------------------------------------------------------------

# 重点检查对象：数字、dataset、sample size、方法名、baseline、性能结论、生物结论、因果 claim、创新 claim
UNSUPPORTED_NUM_PAT = re.compile(r"(?:AUROC|AUC|F1|准确率|精度|accuracy|Pearson|Spearman|R\s*²?)\s*[:=]?\s*(-?\d+\.\d+%?)|p\s*[<=>]\s*(\d+\.\d+%?)", re.I)
CAUSAL_WORDS = ["导致", "引起", "因果", "causal", "cause", "证明因果"]
CORREL_WORDS = ["相关", "关联", "correlat", "associat"]


def unsupported_claim_gate(canonical: Any, deep_text: str, plain_text: str) -> Dict[str, Any]:
    """检查笔记中的重要数字是否在 Canonical 中有依据；检查 correlation 是否被写成 causality。"""
    issues = []
    # 收集 canonical 全部数值（含 data/methods/results），百分比按 ×100 归一化以便与笔记 "89%" 比较
    canon_numbers = set()
    for _, _, v, _, _ in canonical.iter_facts():
        if isinstance(v, (int, float)):
            canon_numbers.add(round(float(v), 3))
    # 额外加入 results 中带 % unit 的归一化值
    for r in getattr(canonical, "results", []) or []:
        rv = r.get("value") if isinstance(r, dict) else getattr(r, "value", None)
        ru = (r.get("unit") if isinstance(r, dict) else None) or ""
        if isinstance(rv, (int, float)) and "%" in str(ru):
            canon_numbers.add(round(float(rv) * 100.0, 3))
    # 笔记中大数字若 canonical 没有 -> 疑似编造（仅对"看起来像指标"的数字告警，避免误伤年份/页码）
    for label, txt in (("deep", deep_text), ("plain", plain_text)):
        for m in UNSUPPORTED_NUM_PAT.finditer(txt):
            raw = m.group(1) or m.group(2)
            if not raw:
                continue
            num = round(float(raw.rstrip("%")), 3)
            # 年份类（1900-2100）跳过
            if 1900 <= num <= 2100:
                continue
            # 容忍 %/万/亿 量级后在 canonical 中查找
            if not any(_num_equal_scale(num, cv) for cv in canon_numbers):
                issues.append({
                    "location": label, "type": "UNSUPPORTED_NUMBER",
                    "value": raw,
                    "reason": f"笔记出现数值 {raw}，但在 Canonical 事实层找不到对应依据（疑似编造或转录错误）",
                })
        # correlation -> causality 检查
        for cw in CAUSAL_WORDS:
            if cw.lower() in txt.lower():
                # 同段是否也出现相关词（说明作者谨慎）；否则可能过度推断
                if not any(k in txt.lower() for k in CORREL_WORDS):
                    issues.append({
                        "location": label, "type": "CAUSAL_OVERCLAIM",
                        "value": cw,
                        "reason": f"笔记出现因果表述 '{cw}'，但未同时标注其为相关性/关联性，可能将 correlation 写成 causality",
                    })
    status = FAIL if issues else PASS
    return {
        "status": status,
        "issues": issues,
        "reason": "未发现明显无依据宣称" if status == PASS else "发现疑似无依据宣称",
    }


# ---------------------------------------------------------------------------
# 4. Professional <-> Plain Alignment Gate
# ---------------------------------------------------------------------------

# 配对节：专业与白话应解释同一对象。这里用"共享专有名词/方法名"衡量语义一致性。
def _propernouns(text: str) -> set:
    """提取文本中的可能专有名词（大写开头英文词 / 含大写缩写 / 中文术语）。"""
    tokens = set()
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9]{2,}\b", text):
        tokens.add(m.group(0))
    # 中文连续术语（4字以上）粗略提取
    for m in re.finditer(r"[\u4e00-\u9fff]{4,}", text):
        tokens.add(m.group(0))
    return tokens


def alignment_gate(deep_text: str, plain_text: str, canonical: Any) -> Dict[str, Any]:
    """检查专业与白话是否解释同一组核心对象（共享专有名词比例）。"""
    # 从 canonical 取核心方法/数据集名作为"应被两边共同提及"的锚
    anchors = set()
    for m in getattr(canonical, "methods", []) or []:
        nm = m.get("name") if isinstance(m, dict) else getattr(m, "name", None)
        if nm:
            anchors.add(str(nm))
    for d in getattr(canonical, "data", []) or []:
        nm = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
        if nm:
            anchors.add(str(nm))
    anchors |= _propernouns(deep_text) & _propernouns(plain_text)
    # 过滤掉太常见的词
    common = {"The", "This", "However", "Therefore", "Results", "Methods", "Abstract", "作者", "论文", "模型", "方法", "数据", "实验", "结果", "我们", "研究", "本文", "使用", "提出", "发现"}
    anchors = {a for a in anchors if a not in common and len(a) >= 3}

    deep_pn = _propernouns(deep_text)
    plain_pn = _propernouns(plain_text)
    if not anchors:
        # 退化：比较两边专有名词 Jaccard
        inter = len(deep_pn & plain_pn)
        union = len(deep_pn | plain_pn)
        score = inter / union if union else 0.0
        status = PASS if score >= 0.15 else PARTIAL
        return {"status": status, "score": round(score, 3),
                "reason": "无明确锚点，按专有名词重叠率判断（>=0.15 通过）"}
    covered = anchors & deep_pn & plain_pn
    ratio = len(covered) / len(anchors) if anchors else 0.0
    status = PASS if ratio >= 0.5 else (PARTIAL if ratio >= 0.25 else FAIL)
    missing = anchors - (deep_pn & plain_pn)
    return {
        "status": status,
        "anchor_coverage": round(ratio, 3),
        "missing_in_one_side": sorted(missing)[:10],
        "reason": f"核心对象在双方笔记共同覆盖比例={ratio:.2f}（>=0.5 PASS）" if status == PASS
                  else f"核心对象覆盖不足（{ratio:.2f}），以下对象仅在一侧出现：{sorted(missing)[:5]}",
    }


# ---------------------------------------------------------------------------
# 5b. Quick Read Length Gate（仅白话）
# ---------------------------------------------------------------------------

def quick_read_length_gate(plain_text: str) -> Dict[str, Any]:
    """白话笔记应是短篇 Quick Understanding Note，不是第二篇完整拆解。

    中文字数超出上限 -> FAIL（写成深度拆解）；低于下限 -> WARN（敷衍/空话）。
    """
    han = len(re.findall(r"[\u4e00-\u9fff]", plain_text))
    if han > QUICK_READ_MAX_HAN:
        return {"status": FAIL, "han_chars": han,
                "reason": f"白话笔记中文字数 {han} 超过上限 {QUICK_READ_MAX_HAN}，疑似写成完整拆解而非短篇速读"}
    if han < QUICK_READ_MIN_HAN:
        return {"status": PARTIAL, "han_chars": han,
                "reason": f"白话笔记中文字数 {han} 低于下限 {QUICK_READ_MIN_HAN}，内容可能过于敷衍"}
    return {"status": PASS, "han_chars": han,
            "reason": f"白话笔记中文字数 {han} 在合理区间（{QUICK_READ_MIN_HAN}~{QUICK_READ_MAX_HAN}）"}


# ---------------------------------------------------------------------------
# 5c. Not Deep Analysis Duplicate Gate（仅白话）
# ---------------------------------------------------------------------------

def not_deep_analysis_duplicate_gate(plain_text: str) -> Dict[str, Any]:
    """白话笔记不应复刻深度拆解的 #0~#9 长模板结构（即不应写成第二篇完整论文拆解）。"""
    hits = [tok for tok in DEEP_TEMPLATE_FORBIDDEN if tok in plain_text]
    if hits:
        return {"status": FAIL, "hits": hits,
                "reason": f"白话笔记出现深度拆解 #0~#9 模板痕迹：{hits}，应改用轻量双栏速读结构"}
    return {"status": PASS, "hits": [],
            "reason": "未出现 #0~#9 模板，结构合规（短篇双栏速读，非完整拆解）"}


# ---------------------------------------------------------------------------
# 5d. Core Questions Gate（仅白话，六问可答性）
# ---------------------------------------------------------------------------

# 六问及对应的关键词簇：能答出即可，不要求标题机械对应
CORE_QUESTION_CHECKS = {
    "q1_what":        (["研究", "做了什么", "论文", "提出", "重建", "推断", "预测"], 1),
    "q2_why":         (["为什么", "问题", "不足", "挑战", "难以", "缺乏", "局限"], 1),
    "q3_idea":        (["核心", "思路", "想法", "关键", "认为", "观点", "intuition"], 1),
    "q4_how":         (["流程", "步骤", "输入", "输出", "做法", "具体", "先", "再", "最后", "训练"], 1),
    "q5_result":      (["结果", "达到", "高于", "优于", "消融", "发现", "AUROC", "AUPR", "指标"], 1),
    "q6_meaning":     (["贡献", "价值", "意义", "说明", "证明", "边界", "注意", "意味着"], 1),
}


def core_questions_gate(plain_text: str) -> Dict[str, Any]:
    """读者能否只凭白话笔记回答六个核心问题。六问全可答 -> PASS；任一不可答 -> FAIL。"""
    if not plain_text:
        return {"overall": FAIL, "answered": 0, "total": 6,
                "missing": list(CORE_QUESTION_CHECKS.keys()),
                "reason": "白话笔记为空"}
    t = plain_text.lower()
    missing = []
    for q, (kws, mh) in CORE_QUESTION_CHECKS.items():
        ok = _has_meaningful(t, kws, mh)
        if not ok:
            missing.append(q)
    answered = 6 - len(missing)
    status = PASS if not missing else FAIL
    return {
        "overall": status,
        "answered": answered,
        "total": 6,
        "missing": missing,
        "reason": f"六问可答 {answered}/6" + ("" if status == PASS else f"，缺失：{missing}"),
    }


# ---------------------------------------------------------------------------
# 5. Explanation Depth Gate（仅白话）
# ---------------------------------------------------------------------------

def explanation_depth_gate(plain_text: str, canonical: Any) -> Dict[str, Any]:
    """白话不能是"名词替换"。对最核心 1-3 个方法模块检查：是否回答 处理什么/怎么处理/为什么需要/处理后变化。

    综述（REVIEW）适配：被综述的是"方法家族"而非单一模型，白话常以具体工具名（CellPhoneDB 等）叙述，
    跳过严格方法名匹配（返回 NA，不计入 overall FAIL），避免误伤自然叙事。
    """
    paper_type = (getattr(canonical, "paper_type", None) or
                  (canonical.get("paper_type") if isinstance(canonical, dict) else None))
    if paper_type == "REVIEW":
        return {"overall": NA, "status": NA,
                "reason": "综述类型：被综述的是方法家族，白话以具体工具名叙述，跳过严格方法名匹配"}
    # 取 canonical 核心方法名（最多 3 个）
    methods = [m for m in (getattr(canonical, "methods", []) or [])]
    # 排除标准指标缩写（MSE/MAE/RMSE 等）——它们是通用度量，白话笔记用中文解释概念即可，
    # 不要求逐字出现英文缩写，否则会误判"名词替换失败"。真正的模型/方法名仍须解释。
    STD_METRIC_ACR = {"MSE", "MAE", "RMSE", "MAPE", "AUC", "AUROC", "F1", "ROC", "IOU",
                      "PSNR", "SSIM", "BLEU", "ROUGE", "ACC", "R2", "PCC", "SCC"}

    def _method_key(name: str) -> str:
        """方法名匹配键：去括号、取首词、小写，使 'CIFM (Cell-Informed...)' 能匹配 'CIFM'。"""
        base = name.split("(")[0].split("[")[0].strip()
        return base.split()[0].lower() if base.split() else base.lower()

    core = []
    for m in methods[:6]:
        nm = m.get("name") if isinstance(m, dict) else getattr(m, "name", None)
        if not nm:
            continue
        key = _method_key(nm)
        alias = (m.get("plain_alias") if isinstance(m, dict) else getattr(m, "plain_alias", None)) or ""
        if key in STD_METRIC_ACR:
            continue
        core.append((nm, key, alias.lower()))
        if len(core) >= 3:
            break
    if not core:
        return {"overall": NA, "status": NA, "reason": "Canonical 无核心方法，跳过"}
    report = {}
    overall = PASS
    for nm, key, alias in core:
        # 白话中是否出现该方法名（匹配键 或 中文别名，允许别名作为子串以兼容略写）
        pt = plain_text.lower()
        present = (key in pt) or (alias and (alias in pt or any(
            alias[i:i+4] in pt for i in range(0, max(0, len(alias)-3)))))
        if not present:
            report[nm] = {"status": FAIL, "reason": f"核心方法 '{nm}' 未在白话中出现（匹配键 '{key}'" +
                                                     (f" / 别名 '{alias}'" if alias else "") + "），无法判断是否解释"}
            overall = FAIL
            continue
        # 方法名附近是否出现"处理/输入/输出/步骤/因为/为什么"等解释性词
        seg = plain_text.lower()
        depth_kw = ["输入", "输出", "步骤", "处理", "因为", "为什么", "目的", "作用", "具体来说", "即", "也就是", "相当于", "input", "output", "purpose"]
        hits = sum(1 for k in depth_kw if k in seg)
        ok = hits >= 2
        st = PASS if ok else PARTIAL
        if st == PARTIAL:
            overall = PARTIAL if overall == PASS else overall
        report[nm] = {"status": st, "reason": f"检测到 {hits} 个解释性线索词（>=2 视为真正解释，否则疑似名词替换）"}
    return {"overall": overall, "details": report}


# ---------------------------------------------------------------------------
# 5e. Professional <-> Plain Dual-Layer Alignment Gates（NEW）
#     白话解读 = 每节【专业描述】+【白话解释】双栏 + 末尾【专业术语文白对照】表
# ---------------------------------------------------------------------------

# 白话解读固定节（用于双栏对齐检查）；末尾术语对照表不参与配对
ALIGN_SECTIONS = [
    ("one_sentence_summary", "一句话看懂"),
    ("motivation", "为什么要做"),
    ("core_idea", "核心思路"),
    ("workflow", "大概怎么做"),
    ("results", "做出了什么"),
    ("conclusion", "最终怎么理解"),
]
PRO_MARK = "【专业描述】"
PLAIN_MARK = "【白话解释】"

# 解释价值信号词：白话若真在"解释"，应出现这些连接/展开词（因果/流程/作用/等价）
EXPLAIN_CONNECTORS = ["因为", "为什么", "具体", "输入", "输出", "步骤", "先", "再", "最后",
                     "目的", "作用", "相当于", "也就是", "即", "换句话说", "本质上", "实际上",
                     "从而", "于是", "简单来说", "可以认为", "换句话说", "也就是说", "分阶段",
                     "第一步", "第二步", "第三步", "第四步", "第五步"]


def _count_han(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _split_sections(plain_text: str):
    """按 heading 切分章节，返回 [(title, body), ...]。"""
    heads = list(re.finditer(r'^#{1,4}\s+(.+?)\s*$', plain_text, re.MULTILINE))
    out = []
    for i, h in enumerate(heads):
        title = h.group(1).strip()
        start = h.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(plain_text)
        out.append((title, plain_text[start:end].strip()))
    return out


def _extract_block(section_body: str, mark: str):
    """从章节体中提取 mark 之后的内容，至下一个 **【...】** 标记或章节末尾。"""
    idx = section_body.find(mark)
    if idx < 0:
        return None
    after = section_body[idx + len(mark):]
    after = re.sub(r'^\s*\*{0,2}\s*', '', after)
    nxt = re.search(r'\*\*【', after)
    if nxt:
        return after[:nxt.start()].strip()
    return after.strip()


def _iter_pairs(plain_text):
    """逐个对齐节产出 (key, title, 专业描述, 白话解释)；节缺失则双栏为 None。"""
    sections = _split_sections(plain_text)
    for key, title in ALIGN_SECTIONS:
        sec = next((b for t, b in sections if title in t), None)
        if sec is None:
            yield key, title, None, None
            continue
        pro = _extract_block(sec, PRO_MARK)
        pla = _extract_block(sec, PLAIN_MARK)
        yield key, title, pro, pla


def _pair_alignment(pro_text, plain_text):
    """专业↔白话对象一致性（软检查）：两栏须讲同一对象。"""
    if not pro_text or not plain_text:
        return FAIL, "缺失专业描述或白话解释之一"
    pro_han = _count_han(pro_text)
    plain_han = _count_han(plain_text)
    # 白话明显短于专业描述 -> 可能未充分展开同一对象
    if plain_han < 0.4 * max(pro_han, 1) and pro_han >= 30:
        return PARTIAL, "白话解释明显短于专业描述，可能未充分展开同一对象"
    # 数字锚：专业描述含关键数字，白话应呼应（核心结果不能丢）
    pro_nums = set(re.findall(r'-?\d+\.?\d+', pro_text))
    plain_nums = set(re.findall(r'-?\d+\.?\d+', plain_text))
    if pro_nums and not (pro_nums & plain_nums):
        return PARTIAL, "专业描述含关键数字，白话解释未呼应（可能遗漏核心结果）"
    return PASS, "专业与白话对象一致（共享关键实体/数字）"


def _pair_explanation_value(pro_text, plain_text):
    """白话是否提供超出专业描述的"理解价值"（非名词翻译）。"""
    if not pro_text or not plain_text:
        return NA, "缺失栏，无法评估"
    pro_han = _count_han(pro_text)
    plain_han = _count_han(plain_text)
    if plain_han < 15:
        return FAIL, "白话解释过短，疑似占位/翻译"
    pro_tokens = set(re.findall(r'[\u4e00-\u9fff]{2,}', pro_text))
    plain_tokens = set(re.findall(r'[\u4e00-\u9fff]{2,}', plain_text))
    share = len(pro_tokens & plain_tokens) / len(pro_tokens) if pro_tokens else 0.0
    expanded = plain_han >= pro_han * 1.3
    has_conn = any(c in plain_text for c in EXPLAIN_CONNECTORS)
    # 翻译型判定：术语高度重合 + 无解释展开 + 篇幅未显著增长 -> 只是名词替换
    if (not has_conn) and (not expanded) and share >= 0.55:
        return FAIL, "白话与专业术语高度重合且缺少解释展开（疑似名词翻译而非解释）"
    return PASS, "白话包含解释性展开（连接词/因果/流程 或 篇幅显著长于专业描述）"


def _check_term_table(plain_text):
    """校验末尾【专业术语文白对照】表存在且概念数 5~12。"""
    m = re.search(r'#{1,4}\s*专业术语文白对照', plain_text)
    if not m:
        return {"status": FAIL, "rows": 0, "reason": "缺少【专业术语文白对照】表（三层信息之一缺失）"}
    tail = plain_text[m.start():]
    rows = [ln for ln in tail.splitlines() if re.match(r'^\s*\|.*\|\s*$', ln)]
    data_rows = max(0, len(rows) - 2)
    if data_rows < 5 or data_rows > 12:
        return {"status": PARTIAL, "rows": data_rows,
                "reason": f"术语表概念数 {data_rows}（建议 5~12，避免过简或重述术语词典）"}
    return {"status": PASS, "rows": data_rows, "reason": f"术语对照表 {data_rows} 个概念，合规"}


def professional_plain_alignment_gate(plain_text: str) -> Dict[str, Any]:
    """对每一节 (专业描述 + 白话解释) 配对检查对象一致性，并校验末尾术语对照表。

    输出：
      one_sentence_summary / motivation / core_idea / workflow / results / conclusion
        每个的状态（PASS / PARTIAL / FAIL）
    """
    if not plain_text:
        return {"status": FAIL, "details": {}, "term_table": {"status": FAIL, "reason": "空笔记"},
                "reason": "白话笔记为空"}
    details = {}
    worst = PASS
    for key, title, pro, pla in _iter_pairs(plain_text):
        if pro is None or pla is None:
            details[key] = {"status": FAIL, "reason": f"章节【{title}】缺少专业描述或白话解释双栏"}
            worst = FAIL
            continue
        a, ar = _pair_alignment(pro, pla)
        details[key] = {"status": a, "alignment": a, "reason": ar}
        if a == FAIL:
            worst = FAIL
        elif a == PARTIAL and worst == PASS:
            worst = PARTIAL
    tt = _check_term_table(plain_text)
    if tt["status"] != PASS and worst == PASS:
        worst = tt["status"]
    return {"status": worst, "details": details, "term_table": tt,
            "reason": "各节专业↔白话对齐检查完成" if worst == PASS else "存在未对齐章节或术语表不合规"}


def explanation_value_gate(plain_text: str) -> Dict[str, Any]:
    """对每节白话栏检查其是否提供超出专业描述的"理解价值"（非名词翻译）。

    输出同上分节状态。
    """
    if not plain_text:
        return {"status": FAIL, "details": {}, "reason": "白话笔记为空"}
    details = {}
    worst = PASS
    for key, title, pro, pla in _iter_pairs(plain_text):
        if pro is None or pla is None:
            details[key] = {"status": FAIL, "reason": f"章节【{title}】缺少双栏，无法评估解释价值"}
            worst = FAIL
            continue
        v, vr = _pair_explanation_value(pro, pla)
        details[key] = {"status": v, "reason": vr}
        if v == FAIL:
            worst = FAIL
        elif v == PARTIAL and worst == PASS:
            worst = PARTIAL
    return {"status": worst, "details": details,
            "reason": "各节白话解释均提供额外理解价值" if worst == PASS else "存在翻译型/占位型白话"}


# ---------------------------------------------------------------------------
# 总入口
# ---------------------------------------------------------------------------

def run_semantic_gate(canonical: Any, deep_text: str, plain_text: str,
                      canonical_is_authoritative: bool = True) -> Dict[str, Any]:
    """运行全部语义 Gate，返回结构化报告。

    canonical_is_authoritative:
      True  -> 真实流水线：Canonical 由 Agent 完整产出，unsupported claim 为硬 FAIL。
      False -> 回归 smoke（Canonical 由笔记反抽、可能不完整）：unsupported 降为 WARN，
               不因此判 overall=FAIL（仅提示人工核对）。
    """
    cov_deep = coverage_gate(deep_text, DEEP_REQUIRED, is_plain=False)
    cov_plain = coverage_gate(plain_text, PLAIN_REQUIRED, is_plain=True)
    num = numerical_consistency_gate(canonical, deep_text, plain_text)
    unsupp = unsupported_claim_gate(canonical, deep_text, plain_text)
    align_dp = alignment_gate(deep_text, plain_text, canonical)
    depth = explanation_depth_gate(plain_text, canonical)
    # 白话专属新检查
    qlen = quick_read_length_gate(plain_text)
    not_dup = not_deep_analysis_duplicate_gate(plain_text)
    core_q = core_questions_gate(plain_text)
    # 双栏速读对齐 + 解释价值（替代旧的 STYLE_SEPARATION_GATE）
    align = professional_plain_alignment_gate(plain_text)
    value = explanation_value_gate(plain_text)

    # unsupported 在降级模式下软处理
    if not canonical_is_authoritative and unsupp["status"] == FAIL:
        unsupp = dict(unsupp)
        unsupp["status"] = PARTIAL
        unsupp["note"] = "Canonical 为反抽降级版，unsupported 仅作 WARN（真实流水线为硬 FAIL）"

    report = {
        "deep_note": {
            "coverage": cov_deep["overall"],
            "coverage_details": cov_deep["details"],
        },
        "plain_note": {
            "problem_explanation": cov_plain["details"].get("problem", {}).get("status", NA),
            "motivation": cov_plain["details"].get("motivation", {}).get("status", NA),
            "core_idea": cov_plain["details"].get("core_idea", {}).get("status", NA),
            "workflow": cov_plain["details"].get("workflow", {}).get("status", NA),
            "result_explanation": cov_plain["details"].get("results", {}).get("status", NA),
            "reasoning": cov_plain["details"].get("reasoning", {}).get("status", NA),
            "professional_plain_alignment": align["status"],
            "explanation_value": value["status"],
            "explanation_depth": depth["overall"],
            "quick_read_length": qlen["status"],
            "quick_read_han_chars": qlen["han_chars"],
            "not_deep_analysis_duplicate": not_dup["status"],
            "core_questions_answered": core_q["answered"],
            "core_questions_total": core_q["total"],
        },
        "facts": {
            "numerical_consistency": num["status"],
            "numerical_details": num,
            "unsupported_claims": unsupp["status"],
            "unsupported_details": unsupp,
        },
        "alignment_details": align_dp,
        "depth_details": depth,
        "quick_read_details": qlen,
        "not_deep_duplicate_details": not_dup,
        "core_questions_details": core_q,
        "professional_plain_alignment_details": align,
        "explanation_value_details": value,
        "canonical_is_authoritative": canonical_is_authoritative,
    }
    # overall
    parts = [cov_deep["overall"], cov_plain["overall"], num["status"], unsupp["status"],
             align_dp["status"], depth["overall"], qlen["status"], not_dup["status"],
             core_q["overall"], align["status"], value["status"]]
    decisive = [p for p in parts if p != NA]
    overall = PASS if all(p == PASS or p == PARTIAL for p in decisive) and FAIL not in decisive else FAIL
    report["overall"] = overall
    return report


if __name__ == "__main__":
    # 自测：人为构造数字错误
    from .model import CanonicalPaper, Evidence
    c = CanonicalPaper()
    c.methods.append({"name": "CIFM", "type": "GeoGNN", "evidence": None})
    c.results.append({"claim": "AUROC", "value": 0.913, "evidence": Evidence(table="Table 2").to_dict()})
    deep = "我们使用 CIFM 模型，AUROC 达到 0.913。"
    plain = "CIFM 这个模型很厉害，AUROC 是 0.931。"   # 错误数字
    r = run_semantic_gate(c, deep, plain)
    print(json.dumps(r, ensure_ascii=False, indent=2))
