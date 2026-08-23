#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model.py — Canonical Paper Model (事实层)

这是论文流水线的事实层 (single source of truth)。
不同 Renderer (深度拆解 / 白话解读 / 其他视图) 都应从同一份 Canonical 派生，
而不是各自重新理解论文，从而避免数字分歧 / 结论不一致 / 幻觉不匹配。

设计原则：
  - 表达"事实"而非 Markdown 段落
  - 重要事实区分 fact_type（PAPER_FACT / AUTHOR_CLAIM / CODE_FACT / ...）
  - 重要事实带 evidence 锚定（能回到论文中定位来源）
  - 允许不确定性 (KNOWN / PARTIAL / UNKNOWN / INFERRED / CONFLICT)
  - 不为了填满 schema 而编造

所有字段默认 None / [] / "unknown"，优于编造。
"""
from __future__ import annotations
import datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Dict

# ---------------------------------------------------------------------------
# 枚举常量
# ---------------------------------------------------------------------------

# 事实类型：区分"客观事实"与"作者主张/推断/解释"
FACT_TYPE_PAPER = "PAPER_FACT"            # 论文正文明确给出的事实
FACT_TYPE_AUTHOR_CLAIM = "AUTHOR_CLAIM"   # 作者自己的解释/主张/结论
FACT_TYPE_CODE_FACT = "CODE_FACT"         # 官方代码仓库才能确认的信息
FACT_TYPE_SUPP = "SUPPLEMENTARY_FACT"     # Supplementary 中出现的信息
FACT_TYPE_INTERP = "INTERPRETATION"       # 为帮助理解做的解释（人工/模型加的）
FACT_TYPE_INFER = "INFERENCE"             # 根据论文信息的合理推断（必须标识）
FACT_TYPE_UNKNOWN = "UNKNOWN"             # 当前来源无法确定

FACT_TYPES = {
    FACT_TYPE_PAPER, FACT_TYPE_AUTHOR_CLAIM, FACT_TYPE_CODE_FACT,
    FACT_TYPE_SUPP, FACT_TYPE_INTERP, FACT_TYPE_INFER, FACT_TYPE_UNKNOWN,
}

# 确定性 / 不确定性
CERTAIN_KNOWN = "KNOWN"        # 来源明确给出
CERTAIN_PARTIAL = "PARTIAL"    # 部分可知
CERTAIN_UNKNOWN = "UNKNOWN"    # 无法确定
CERTAIN_INFERRED = "INFERRED"  # 推断得到（须由 fact_type=INFERENCE 配合）
CERTAIN_CONFLICT = "CONFLICT"  # 多来源冲突，候选人保存于 candidate_values

# 证据来源可信度层级
TIER_PAPER = 1        # 正式论文 PDF / 期刊正文
TIER_SUPP_CODE = 2    # Supplementary / 官方代码
TIER_PREPRINT = 3     # arXiv / bioRxiv（若其为唯一正式版本，则可作为 primary paper）
TIER_PROJECT = 4      # 作者项目主页
TIER_DISCOVERY = 5    # 公众号 / B站 / 新闻 / 博客（仅用于定位，不作证据）

# 关系类型（P1 预留，本轮不自动构建关系图）
REL_EXTENDS = "EXTENDS"
REL_USES_METHOD = "USES_METHOD_FROM"
REL_USES_DATASET = "USES_DATASET_FROM"
REL_COMPARES = "COMPARES_WITH"
REL_CITES = "CITES"
REL_PREPRINT_OF = "PREPRINT_OF"
REL_RELATED_TASK = "RELATED_TASK"

PIPELINE_VERSION = "paper-pipeline-v3"
CANONICAL_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 基础结构
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """证据锚定：让一个事实能回到论文中定位来源。

    不复制论文原文，只记录定位信息。
    若无法精确定位（如只知道来源文档），用 location_precision='document' 而非伪造页码。
    """
    source_type: str = "paper"          # paper / supplementary / code / arxiv / project_page
    source_id: Optional[str] = None     # 关联的 source manifest id（见 source_manifest）
    section: Optional[str] = None
    subsection: Optional[str] = None
    page: Optional[int] = None          # 如能稳定获得 PDF 页码才填
    figure: Optional[str] = None
    table: Optional[str] = None
    supplementary: Optional[str] = None
    quote_or_anchor: Optional[str] = None   # 关键词 / 原文片段锚点，便于人工回查
    location_precision: str = "section"    # document / section / page

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class Fact:
    """一条带类型与证据的事实。"""
    key: str
    value: Any
    fact_type: str = FACT_TYPE_PAPER
    certainty: str = CERTAIN_KNOWN
    evidence: Optional[Evidence] = None
    note: Optional[str] = None           # 解释 / 冲突说明
    candidate_values: Optional[List[Any]] = None  # 当 certainty=CONFLICT 时保存候选

    def to_dict(self) -> dict:
        d = {
            "key": self.key,
            "value": self.value,
            "fact_type": self.fact_type,
            "certainty": self.certainty,
        }
        if self.evidence is not None:
            d["evidence"] = self.evidence.to_dict()
        if self.note is not None:
            d["note"] = self.note
        if self.candidate_values is not None:
            d["candidate_values"] = self.candidate_values
        return d


@dataclass
class Identity:
    """论文身份（用于去重与 Canonical ID 解析）。"""
    title: Optional[str] = None
    normalized_title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    pmid: Optional[str] = None
    canonical_paper_id: Optional[str] = None  # 内部稳定身份标识

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k in ("authors",)}


@dataclass
class SourceRef:
    """一个数据/方法/实验的来源引用（用于 evidence.source_id 关联）。"""
    type: str = "journal"   # journal / pdf / supplementary / code / arxiv / project_page / discovery
    url: Optional[str] = None
    local_path: Optional[str] = None
    status: str = "pending"  # pending / fetched / failed / unused


@dataclass
class RelationSlot:
    """关系预留（P1 仅 schema，不自动构建图）。"""
    type: str = REL_RELATED_TASK
    target: Optional[str] = None          # 目标 canonical_paper_id 或外部引用
    evidence: Optional[str] = None
    confidence: str = CERTAIN_UNKNOWN


# ---------------------------------------------------------------------------
# Canonical Paper Model
# ---------------------------------------------------------------------------

@dataclass
class CanonicalPaper:
    """论文事实层核心模型。"""
    schema_version: str = CANONICAL_SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION

    identity: Dict[str, Any] = field(default_factory=dict)
    sources: Dict[str, Any] = field(default_factory=dict)
    research: Dict[str, Any] = field(default_factory=dict)
    core_idea: Optional[str] = None

    data: List[Dict[str, Any]] = field(default_factory=list)
    methods: List[Dict[str, Any]] = field(default_factory=list)
    workflow: List[Dict[str, Any]] = field(default_factory=list)
    training: Dict[str, Any] = field(default_factory=dict)
    experiments: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    ablations: List[Dict[str, Any]] = field(default_factory=list)
    innovations: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[Dict[str, Any]] = field(default_factory=list)
    author_claims: List[Dict[str, Any]] = field(default_factory=list)
    interpretive_notes: List[Dict[str, Any]] = field(default_factory=list)
    important_terms: List[Dict[str, Any]] = field(default_factory=list)

    # 关系预留（不自动构建图）
    relations: List[Dict[str, Any]] = field(default_factory=list)

    # 关键事实清单（确定性高、若写错则笔记失真）
    critical_facts: List[str] = field(default_factory=list)

    # 自由扩展（避免硬 schema 限制，同时保留结构）
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str) -> None:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "CanonicalPaper":
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        obj = cls()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        return obj

    # --- 便捷查询：抽取所有结构化的"事实条目"（供 gate 使用） ---
    def iter_facts(self):
        """遍历模型中的关键数值/事实，产出 (section, key, value, fact_type, evidence) 。"""
        # identity
        for k in ("title", "authors", "year", "venue", "doi", "arxiv_id", "pmid"):
            v = self.identity.get(k)
            if v is not None:
                yield ("identity", k, v, FACT_TYPE_PAPER, None)
        # research
        for k, v in self.research.items():
            if v is not None and v != "":
                yield ("research", k, v, FACT_TYPE_PAPER, None)
        # data
        for i, d in enumerate(self.data):
            for k, v in d.items():
                if k in ("name", "sample_size", "type", "source", "split") and v not in (None, ""):
                    yield ("data", f"data[{i}].{k}", v, FACT_TYPE_PAPER, d.get("evidence"))
        # methods
        for i, m in enumerate(self.methods):
            for k, v in m.items():
                if k in ("name", "type", "purpose") and v not in (None, ""):
                    yield ("methods", f"methods[{i}].{k}", v, FACT_TYPE_PAPER, m.get("evidence"))
        # workflow
        for i, w in enumerate(self.workflow):
            if w.get("step") is not None:
                yield ("workflow", f"workflow[{i}].step", w.get("step"), FACT_TYPE_PAPER, w.get("evidence"))
        # experiments
        for i, e in enumerate(self.experiments):
            for k, v in e.items():
                if k in ("experiment", "dataset", "baseline", "metric") and v not in (None, ""):
                    yield ("experiments", f"experiments[{i}].{k}", v, FACT_TYPE_PAPER, e.get("evidence"))
        # results (重点：数值)
        for i, r in enumerate(self.results):
            claim = r.get("claim")
            if claim is not None:
                yield ("results", f"results[{i}].claim", claim, FACT_TYPE_PAPER, r.get("evidence"))
            q = r.get("quantitative")
            val = r.get("value")
            if q is not None or val is not None:
                yield ("results", f"results[{i}].value", val if val is not None else q,
                       FACT_TYPE_PAPER, r.get("evidence"))
        # ablations
        for i, a in enumerate(self.ablations):
            if a.get("finding") is not None:
                yield ("ablations", f"ablations[{i}].finding", a.get("finding"), FACT_TYPE_PAPER, a.get("evidence"))
        # innovations
        for i, n in enumerate(self.innovations):
            if n.get("claim") is not None:
                yield ("innovations", f"innovations[{i}].claim", n.get("claim"), FACT_TYPE_AUTHOR_CLAIM, n.get("evidence"))
        # limitations
        for i, l in enumerate(self.limitations):
            if l.get("point") is not None:
                yield ("limitations", f"limitations[{i}].point", l.get("point"), FACT_TYPE_PAPER, l.get("evidence"))
        # author_claims
        for i, c in enumerate(self.author_claims):
            if c.get("claim") is not None:
                yield ("author_claims", f"author_claims[{i}].claim", c.get("claim"), FACT_TYPE_AUTHOR_CLAIM, c.get("evidence"))
        # terms
        for i, t in enumerate(self.important_terms):
            if t.get("term") is not None:
                yield ("important_terms", f"terms[{i}].term", t.get("term"), FACT_TYPE_PAPER, t.get("evidence"))


def normalize_title(title: str) -> str:
    """归一化标题用于去重比较（小写、去标点、压缩空白）。"""
    import re, unicodedata
    t = unicodedata.normalize("NFKD", title)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def resolve_canonical_id(identity: Dict[str, Any]) -> str:
    """Canonical Paper ID 解析，优先级 DOI > arXiv > PMID > normalized title+year > title hash。"""
    doi = identity.get("doi")
    if doi:
        return "doi:" + str(doi).strip().lower()
    arxiv = identity.get("arxiv_id")
    if arxiv:
        return "arxiv:" + str(arxiv).strip().lower()
    pmid = identity.get("pmid")
    if pmid:
        return "pmid:" + str(pmid).strip()
    title = identity.get("normalized_title") or identity.get("title")
    year = identity.get("year")
    if title:
        nt = normalize_title(title)
        if year:
            return "title:%s:%s" % (nt, year)
        # 稳定 hash 兜底
        import hashlib
        return "hash:" + hashlib.sha1(nt.encode("utf-8")).hexdigest()[:16]
    return "unknown"


if __name__ == "__main__":
    # 自测
    c = CanonicalPaper()
    c.identity = {"title": "Test Paper", "year": 2026, "doi": "10.1234/test"}
    c.identity["canonical_paper_id"] = resolve_canonical_id(c.identity)
    c.core_idea = "A test idea"
    c.results.append({"claim": "AUROC", "value": 0.913, "unit": "",
                      "evidence": Evidence(table="Table 2", section="Results").to_dict()})
    c.critical_facts = ["core_method", "main_result"]
    print("canonical_id =", c.identity["canonical_paper_id"])
    print("facts:", list(c.iter_facts()))
    c.save("/tmp/_c_test.json")
    c2 = CanonicalPaper.load("/tmp/_c_test.json")
    print("roundtrip ok:", c2.identity["canonical_paper_id"] == c.identity["canonical_paper_id"])
