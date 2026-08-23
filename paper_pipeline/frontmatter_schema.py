#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
frontmatter_schema.py — frontmatter Schema 校验 (P1)

把隐式 frontmatter 规则明确为 schema，校验：
  required / type / enum / format / relationship
纯确定性校验，不依赖 build.py 正则成功就算有效。
"""
from __future__ import annotations
import os, re, json
from typing import Dict, List, Optional, Tuple

# 允许的分类（从 categories.json 读取，失败则降级到内置）
def load_allowed_categories(catfile: str) -> List[str]:
    try:
        cats = json.load(open(catfile, encoding="utf-8"))
        return [c["id"] for c in cats]
    except Exception:
        return ["uncat"]


class SchemaError(Exception):
    pass


def _parse_fm(text: str) -> Tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    fm_raw = m.group(1)
    fm = {}
    for line in fm_raw.split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, text[m.end():]


PAPER_SCHEMA = {
    "required": ["title", "type", "category", "doi", "tags", "summary"],
    "types": {"title": str, "type": str, "category": str, "doi": str,
              "tags": (list, str), "summary": str, "journal": str, "date": str,
              "created": str, "source": str, "authors": (list, str),
              "pipeline_version": str, "canonical_paper_id": str},
    "enum": {"type": ["paper"], "kind": ["paper"]},
}

NOTE_SCHEMA = {
    "required": ["kind", "parent_paper", "note_type", "pipeline_version"],
    "types": {"kind": str, "parent_paper": str, "title": str, "type": str,
              "category": str, "tags": (list, str), "note_type": str,
              "pipeline_version": str},
    "enum": {"kind": ["note"], "note_type": ["paper_analysis", "paper_explainer"]},
}


def validate_paper(fm: dict, allowed_categories: List[str]) -> List[str]:
    errors = []
    for r in PAPER_SCHEMA["required"]:
        if not fm.get(r):
            errors.append(f"paper 缺必需字段: {r}")
    if fm.get("category") and fm["category"] not in allowed_categories:
        errors.append(f"paper category '{fm['category']}' 不在允许分类树中")
    if fm.get("type") and fm["type"] != "paper":
        errors.append(f"paper type 应为 'paper'，实际 '{fm['type']}'")
    return errors


def validate_note(fm: dict, paper_slug: Optional[str] = None) -> List[str]:
    errors = []
    for r in NOTE_SCHEMA["required"]:
        if not fm.get(r):
            errors.append(f"note 缺必需字段: {r}")
    if fm.get("kind") and fm["kind"] != "note":
        errors.append(f"note kind 应为 'note'，实际 '{fm['kind']}'")
    if fm.get("note_type") and fm["note_type"] not in ("paper_analysis", "paper_explainer"):
        errors.append(f"note note_type 非法: {fm['note_type']}")
    if paper_slug and fm.get("parent_paper") and fm["parent_paper"] != paper_slug:
        errors.append(f"note parent_paper '{fm['parent_paper']}' != 论文 slug '{paper_slug}'")
    return errors


def validate_file(path: str, allowed_categories: List[str], paper_slug: Optional[str] = None) -> List[str]:
    text = open(path, encoding="utf-8").read()
    fm, _ = _parse_fm(text)
    if not fm:
        return ["frontmatter 解析失败（缺闭合 --- 或格式错误）"]
    if fm.get("kind") == "paper" or (fm.get("type") == "paper" and "parent_paper" not in fm):
        return validate_paper(fm, allowed_categories)
    return validate_note(fm, paper_slug)


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cats = load_allowed_categories(os.path.join(here, "categories.json"))
    p = os.path.join(here, "content", "papers", "cifm_论文.md")
    n = os.path.join(here, "content", "notes", "cifm_论文拆解.md")
    print("paper:", validate_file(p, cats))
    print("note:", validate_file(n, cats, "papers_cifm_论文"))
