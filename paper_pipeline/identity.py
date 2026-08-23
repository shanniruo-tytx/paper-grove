#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
identity.py — 论文唯一标识解析 + 重复导入防护 (Duplicate Gate)

canonical_paper_id 优先级：DOI > arXiv > PMID > normalized title+year > title hash
注意：canonical_paper_id 用于"论文身份确认"，与 KB 前端 slug (papers_{简称}_论文) 不同概念，
本模块不修改任何已有 slug。

Duplicate Gate 判定：
  NEW                : 全新论文
  EXACT_DUPLICATE   : DOI/arXiv/PMID 一致 -> 默认不创建第二篇
  POSSIBLE_DUPLICATE: 无稳定 ID，但 normalized title(+year/作者) 高度一致 -> 停止自动重复导入，报告候选
  VERSION_UPDATE     : 例如 arXiv preprint -> 正式期刊版本 -> 建立关联，不静默重复创建
"""
from __future__ import annotations
import json, os, re
from typing import Optional
from .model import normalize_title, resolve_canonical_id

DUP_NEW = "NEW"
DUP_EXACT = "EXACT_DUPLICATE"
DUP_POSSIBLE = "POSSIBLE_DUPLICATE"
DUP_VERSION = "VERSION_UPDATE"


def title_similarity(a: str, b: str) -> float:
    """基于归一化标题的 token Jaccard 相似度。"""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    sa, sb = set(na.split()), set(nb.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def resolve_identity(fm: dict) -> dict:
    """从论文 frontmatter 解析 identity dict。"""
    title = fm.get("title")
    authors_raw = fm.get("authors")
    if isinstance(authors_raw, str):
        authors = [a.strip() for a in re.split(r"[,;]", authors_raw) if a.strip()]
    elif isinstance(authors_raw, list):
        authors = [str(a).strip() for a in authors_raw if str(a).strip()]
    else:
        authors = []
    year = None
    date = fm.get("date", "")
    m = re.search(r"(\d{4})", str(date))
    if m:
        year = int(m.group(1))
    ident = {
        "title": title,
        "normalized_title": normalize_title(title) if title else None,
        "authors": authors,
        "year": year,
        "venue": fm.get("journal") or fm.get("venue"),
        "doi": (fm.get("doi") or "").strip() or None,
        "arxiv_id": (fm.get("arxiv_id") or fm.get("arxivId") or "").strip() or None,
        "pmid": (fm.get("pmid") or "").strip() or None,
    }
    ident["canonical_paper_id"] = resolve_canonical_id(ident)
    return ident


def scan_existing_papers(content_dir: str):
    """扫描 content/papers 下所有论文，返回 [(slug, identity, fm)] 。"""
    out = []
    papers_dir = os.path.join(content_dir, "papers")
    if not os.path.isdir(papers_dir):
        return out
    for fn in os.listdir(papers_dir):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(papers_dir, fn)
        text = open(p, encoding="utf-8").read()
        # 轻量 frontmatter 解析（不必走 build.py 的完整逻辑）
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        fm = {}
        if m:
            for line in m.group(1).split("\n"):
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
        slug = "papers_" + fn[:-3]
        out.append((slug, resolve_identity(fm), fm))
    return out


def duplicate_check(new_identity: dict, existing) -> dict:
    """对 new_identity 在 existing 列表中做去重判定。

    返回：
      {
        "decision": NEW/EXACT_DUPLICATE/POSSIBLE_DUPLICATE/VERSION_UPDATE,
        "matched_slug": ..., "matched_id": ..., "similarity": ...,
        "reason": ...
      }
    """
    new_id = new_identity.get("canonical_paper_id", "")
    new_doi = new_identity.get("doi")
    new_arxiv = new_identity.get("arxiv_id")
    new_pmid = new_identity.get("pmid")
    new_norm = new_identity.get("normalized_title")
    new_year = new_identity.get("year")
    new_authors = set(a.lower() for a in new_identity.get("authors", []))

    best = None
    for slug, ex_ident, ex_fm in existing:
        ex_id = ex_ident.get("canonical_paper_id", "")

        # 稳定 ID 完全一致 -> EXACT
        stable_keys = [("doi", new_doi, ex_ident.get("doi")),
                       ("arxiv", new_arxiv, ex_ident.get("arxiv_id")),
                       ("pmid", new_pmid, ex_ident.get("pmid"))]
        for label, nv, ev in stable_keys:
            if nv and ev and str(nv).strip().lower() == str(ev).strip().lower():
                # 区分 VERSION_UPDATE：同一 arXiv 但 venue 从 preprint 变 journal
                ex_venue = (ex_ident.get("venue") or "").lower()
                new_venue = (new_identity.get("venue") or "").lower()
                if ("arxiv" in ex_id or "arxiv" in ex_id) and new_venue and "arxiv" not in new_venue and "biorxiv" not in new_venue and "preprint" not in new_venue:
                    return {"decision": DUP_VERSION, "matched_slug": slug, "matched_id": ex_id,
                            "similarity": 1.0,
                            "reason": f"同一 arXiv({nv})，但目标 venue='{new_venue}' 与已收录 venue='{ex_venue}' 不同，疑似 preprint->期刊版本更新"}
                return {"decision": DUP_EXACT, "matched_slug": slug, "matched_id": ex_id,
                        "similarity": 1.0,
                        "reason": f"稳定 ID 一致 ({label}={nv})，判定为同一篇论文"}

        # 无稳定 ID：标题相似 + (年份或作者)一致 -> POSSIBLE
        if new_norm and ex_ident.get("normalized_title"):
            sim = title_similarity(new_identity.get("title", ""), ex_ident.get("title", ""))
            ex_authors = set(a.lower() for a in ex_ident.get("authors", []))
            year_match = (new_year and ex_ident.get("year") and new_year == ex_ident.get("year"))
            author_overlap = len(new_authors & ex_authors) > 0
            if sim >= 0.85 and (year_match or author_overlap or sim >= 0.95):
                cand = {"decision": DUP_POSSIBLE, "matched_slug": slug, "matched_id": ex_id,
                        "similarity": round(sim, 3),
                        "reason": f"归一化标题相似度={sim:.2f}" +
                                  ("，年份一致" if year_match else "") +
                                  ("，作者重叠" if author_overlap else "")}
                # 选最高相似度的候选
                if best is None or cand["similarity"] > best["similarity"]:
                    best = cand

    if best is not None:
        return best
    return {"decision": DUP_NEW, "matched_slug": None, "matched_id": None,
            "similarity": 0.0, "reason": "未在任何已有论文中找到匹配"}


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    existing = scan_existing_papers(os.path.join(here, "content"))
    print("已收录论文数:", len(existing))
    # 模拟重复：用 cifm 的 doi 再查一次
    cifm = next((e for e in existing if e[2].get("doi") == "10.64898/2026.08.12.743536"), None)
    if cifm:
        res = duplicate_check(cifm[1], existing)
        print("CIFM 重复检测:", res["decision"], res["matched_slug"])
