#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source_manifest.py — 来源清单 (Source Manifest)

记录每次运行到底"读到了什么材料"，让后续看到一篇笔记时，能知道当时 Harness 的真实输入，
而不是只看到最后的 Markdown。

discovery source (公众号/B站) != evidence source (论文正文/supplementary/代码)。
"""
from __future__ import annotations
import json, os, datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import List, Optional

STATUS_PENDING = "pending"
STATUS_FETCHED = "fetched"
STATUS_FAILED = "failed"
STATUS_UNUSED = "unused"


@dataclass
class SourceItem:
    type: str                       # journal / pdf / supplementary / code / arxiv / project_page / discovery
    url: Optional[str] = None
    local_path: Optional[str] = None
    status: str = STATUS_PENDING
    tier: int = 5                   # 可信度层级 (1最高)
    role: str = "discovery"         # discovery / evidence
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class SourceManifest:
    input_url: Optional[str] = None
    resolved_paper: Optional[str] = None     # canonical_paper_id 或标题
    sources: List[dict] = field(default_factory=list)
    retrieved_at: str = field(default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds"))

    def add(self, item: SourceItem):
        self.sources.append(item.to_dict())

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "SourceManifest":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        obj = cls()
        for k, v in d.items():
            setattr(obj, k, v)
        return obj


def build_manifest(input_url: str, identity: dict, sources: List[SourceItem]) -> SourceManifest:
    """构造一份来源清单。"""
    m = SourceManifest(input_url=input_url, resolved_paper=identity.get("canonical_paper_id") or identity.get("title"))
    for s in sources:
        m.add(s)
    return m


if __name__ == "__main__":
    items = [
        SourceItem("discovery", url="https://mp.weixin.qq.com/s/xxx", tier=5, role="discovery"),
        SourceItem("pdf", url="https://www.biorxiv.org/content/10.64898/2026.08.12.743536", tier=1, role="evidence", status="fetched"),
    ]
    m = build_manifest("https://mp.weixin.qq.com/s/xxx", {"canonical_paper_id": "doi:10.64898/2026.08.12.743536"}, items)
    print(json.dumps(m.to_dict(), ensure_ascii=False, indent=2))
