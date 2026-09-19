#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析规则（skill / prompt）同步。

为什么需要它：
    解析规则有三处副本，换机器时最容易丢的是「本地执行副本」：

      1. Hub 规范源   harness-management/harnesses/article-summarizer/  (另一个项目)
      2. 仓库副本     kb-site/harness/article-summarizer/               ← 随 git 走，换机器一定有
      3. 执行副本     kb-site/.workbuddy/skills/                        ← .gitignore 排除，换机器后为空

    本脚本把 1 或 2 灌到 3，让 agent 在新机器上照样按同一套规则解析。

用法：
    python scripts/sync_skills.py              # 仓库副本 -> 执行副本（默认，离线可用）
    python scripts/sync_skills.py --from-hub   # 优先从 Hub(4173) 拉，不可达则回退仓库副本
    python scripts/sync_skills.py --to-repo    # 反向：执行副本 -> 仓库副本（本地改完想入库时用）
    python scripts/sync_skills.py --dry-run    # 只看会写什么
    python scripts/sync_skills.py --quiet      # 静默（deploy.py 内部调用）

deploy.py 会在构建前自动跑一次（默认模式），无需手动执行。
"""
import os
import sys
import json
import argparse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "harness", "article-summarizer")
SKILLS = os.path.join(ROOT, ".workbuddy", "skills")
HUB = "http://127.0.0.1:4173"

# 仓库/Harness 内相对路径 -> 执行副本路径
MAP = [
    ("skills/article-summarizer.md", ".workbuddy/skills/article-summarizer/SKILL.md"),
    ("skills/paper-locator.md",      ".workbuddy/skills/paper-locator/SKILL.md"),
    ("skills/paper-reader.md",       ".workbuddy/skills/paper-reader/SKILL.md"),
    ("prompts/summary-format.md",    ".workbuddy/skills/article-summarizer/summary-format.md"),
]


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path, content, quiet=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = _read(path) if os.path.exists(path) else None
    if old == content:
        if not quiet:
            print("      = 未变化  %s" % os.path.relpath(path, ROOT))
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    if not quiet:
        verb = "已更新" if old is not None else "已新建"
        print("      ✓ %s  %s" % (verb, os.path.relpath(path, ROOT)))
    return True


def hub_files(timeout=1.5):
    """从 Hub 拉 harness 文件，返回 {path: content}；不可达返回 None。"""
    url = "%s/api/harnesses/article-summarizer/files" % HUB
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = {}
        for f in data.get("files", []):
            out[f.get("path")] = f.get("content", "")
        return out or None
    except Exception:
        return None


def sync(args):
    quiet = args.quiet
    hub = None
    label = "执行副本 -> 仓库副本" if args.to_repo else "仓库副本 -> 执行副本"
    if args.from_hub and not args.to_repo:
        hub = hub_files()
        label = "Hub(4173) -> 执行副本" if hub else "Hub 不可达，回退：仓库副本 -> 执行副本"

    if not quiet:
        print("  解析规则同步（%s）" % label)

    n = 0
    for rel_harness, rel_local in MAP:
        # rel_harness: harness 内路径（skills/xxx.md）
        # rel_local  : 仓库内执行副本路径（.workbuddy/skills/...）
        if args.to_repo:
            src = os.path.join(ROOT, rel_local)
            dst = os.path.join(HARNESS, rel_harness)
            src_label, dst_label = rel_local, "harness/" + rel_harness
            if not os.path.exists(src):
                if not quiet:
                    print("      - 跳过（源不存在） %s" % src_label)
                continue
            content = _read(src)
        else:
            if hub is not None and rel_harness in hub:
                content = hub[rel_harness]
                src_label = "hub:" + rel_harness
            else:
                src = os.path.join(HARNESS, rel_harness)
                src_label = "harness/" + rel_harness
                if not os.path.exists(src):
                    if not quiet:
                        print("      - 跳过（源不存在） %s" % src_label)
                    continue
                content = _read(src)
            dst = os.path.join(ROOT, rel_local)
            dst_label = rel_local

        if args.dry_run:
            print("      [dry-run] %s  ->  %s  (%d chars)" % (src_label, dst_label, len(content)))
            n += 1
            continue
        if _write(dst, content, quiet=quiet):
            n += 1

    if not quiet:
        print("      %s %d 个文件" % ("[dry-run] 将写入" if args.dry_run else "完成，变更", n))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="解析规则（skill/prompt）同步")
    ap.add_argument("--from-hub", action="store_true", help="优先从 Hub(4173) 拉取")
    ap.add_argument("--to-repo", action="store_true", help="反向：执行副本 -> 仓库副本")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要写入的文件")
    ap.add_argument("--quiet", action="store_true", help="静默输出")
    args = ap.parse_args(argv)
    return sync(args)


if __name__ == "__main__":
    sys.exit(main())
