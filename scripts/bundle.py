#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容包导出 / 导入（换电脑迁移文献用）。

仓库里 `content/**` 与 `categories.json` 被 .gitignore 排除（属于个人数据），
所以换机器时 clone 下来是空站。本脚本把「内容」单独打成一个 zip 随身带走。

导出（在旧机器 / 当前机器上）：
    python scripts/bundle.py export
    python scripts/bundle.py export --out D:/backup/kb-content.zip

导入（在新机器上，或让 bootstrap 用 -Bundle 自动做）：
    python scripts/bundle.py import D:/backup/kb-content.zip
    python scripts/bundle.py import D:/backup/kb-content.zip --root E:/paper-grove

包内含：
    content/papers/*.md
    content/notes/*.md
    content/resources/*.md
    categories.json（若存在，方便连分类树一起搬）
"""
import os
import sys
import json
import zipfile
import argparse
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBDIRS = ["papers", "notes", "resources"]


def _default_out():
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = os.path.join(ROOT, "_bundle")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "paper-grove-content-%s.zip" % ts)


def cmd_export(args):
    out = args.out or _default_out()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in SUBDIRS:
            d = os.path.join(ROOT, "content", sub)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".md"):
                    continue
                full = os.path.join(d, fn)
                z.write(full, "content/%s/%s" % (sub, fn))
                n += 1
        cat = os.path.join(ROOT, "categories.json")
        if os.path.exists(cat):
            z.write(cat, "categories.json")
            n += 1
    size = os.path.getsize(out) / 1024.0
    print("导出完成：%d 个文件 → %s（%.1f KB）" % (n, out, size / 1024.0 if False else size))
    print("把它拷到新机器，部署时：python scripts/bootstrap.ps1 或 deploy 后执行")
    print("    python scripts/bundle.py import <zip>")
    print("或直接：powershell -File scripts/bootstrap.ps1 -Bundle <zip>")
    return out


def cmd_import(args):
    src = args.zip
    if not os.path.exists(src):
        print("找不到内容包：%s" % src, file=sys.stderr)
        sys.exit(1)
    root = args.root or ROOT
    n = 0
    with zipfile.ZipFile(src, "r") as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            # 防目录穿越：只接受 content/... 与 categories.json
            norm = os.path.normpath(name).replace("\\", "/")
            if norm.startswith("../") or "/../" in norm:
                print("跳过非法路径：%s" % name, file=sys.stderr)
                continue
            if not (norm.startswith("content/") or norm == "categories.json"):
                print("跳过非内容文件：%s" % name, file=sys.stderr)
                continue
            target = os.path.join(root, norm)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(z.read(name))
            n += 1
    print("导入完成：%d 个文件 → %s" % (n, root))
    cat = os.path.join(root, "categories.json")
    if os.path.exists(cat):
        try:
            data = json.load(open(cat, encoding="utf-8"))
            print("分类树：%d 个节点" % len(data))
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="Paper Grove 内容包导出/导入")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("export", help="把 content/ 与 categories.json 打成 zip")
    p1.add_argument("--out", help="输出 zip 路径（默认 _bundle/paper-grove-content-<时间戳>.zip）")
    p1.set_defaults(func=cmd_export)

    p2 = sub.add_parser("import", help="把 zip 解回 content/ 与 categories.json")
    p2.add_argument("zip", help="内容包 zip 路径")
    p2.add_argument("--root", help="目标仓库根目录（默认当前仓库）")
    p2.set_defaults(func=cmd_import)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
