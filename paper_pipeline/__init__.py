#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper_pipeline — 论文流水线事实层 + 质量 Gate + 执行记录。

真实代码实现（非仅 prompt）：
  - model.py            : Canonical Paper Model（事实层，带 fact_type / evidence / uncertainty / relations）
  - identity.py         : Canonical Paper ID 解析 + Duplicate Gate
  - source_manifest.py  : 来源清单
  - semantic_gate.py    : 语义质量 Gate（coverage / numerical / unsupported / alignment / depth）
  - run_manifest.py     : 执行记录 + Resume
  - staging.py          : 阶段性导入 + Rollback
  - frontmatter_schema.py: frontmatter schema 校验
  - run.py              : 编排入口（含 resume）

LLM 驱动的 stage（locator/reader/canonical/renderers）由 Agent 填充内容，
但所有确定性校验、缓存、去重、事务、记录均为可运行代码。
"""
from . import model, identity, source_manifest, semantic_gate, run_manifest, staging, frontmatter_schema

__all__ = ["model", "identity", "source_manifest", "semantic_gate",
           "run_manifest", "staging", "frontmatter_schema"]
