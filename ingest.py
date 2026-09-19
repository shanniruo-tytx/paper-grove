#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口化导入助手（Agent 侧 CLI）。

替代「Agent 直接 Write content/*.md + 本地跑 build.py」的老流程：
Agent 把流水线生成的 markdown 写到任意临时目录（不要直接写 kb-site/content/），
再用本脚本 POST 到 kb-site 的 /api/ingest，由服务端原子落盘并触发 build.py 双闸。

用法：
  python ingest.py "C:/tmp/foo_papers.md@content/papers/foo_论文.md" \
                    "C:/tmp/foo_notes.md@content/notes/foo_论文拆解.md" \
                    "C:/tmp/foo_explain.md@content/notes/foo_论文白话解读.md" \
                    [--url http://127.0.0.1:8766] [--no-build]

  简写：若本地文件本身就在 kb-site/content/ 下，可省略 @target，自动推导目标路径。
  例如：python ingest.py "E:/.../kb-site/content/papers/foo_论文.md"
"""
import sys, os, json, argparse, urllib.request, urllib.error


def main():
    ap = argparse.ArgumentParser(description="POST markdown files to kb-site /api/ingest")
    ap.add_argument("items", nargs="+", help="local.md 或 local.md@content/.../x.md")
    ap.add_argument("--url", default="http://127.0.0.1:8766")
    ap.add_argument("--no-build", action="store_true", help="只落盘，不触发 build.py")
    args = ap.parse_args()

    root_guess = os.path.dirname(os.path.abspath(__file__))
    content_dir = os.path.join(root_guess, "content")

    files = []
    for it in args.items:
        if "@" in it:
            local, target = it.split("@", 1)
        else:
            local = it
            ap_path = os.path.abspath(local)
            if ap_path.startswith(content_dir):
                rel = os.path.relpath(ap_path, content_dir).replace("\\", "/")
                target = "content/" + rel
            else:
                sys.exit("错误：%s 不在 content/ 下，且未用 @ 指定目标路径" % local)
        target = target.strip().replace("\\", "/").lstrip("/")
        if not os.path.isfile(local):
            sys.exit("错误：本地文件不存在：%s" % local)
        if not target.endswith(".md"):
            sys.exit("错误：目标路径须以 .md 结尾：%s" % target)
        content = open(local, encoding="utf-8").read()
        files.append({"path": target, "content": content})

    payload = {"files": files, "build": not args.no_build}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = args.url.rstrip("/") + "/api/ingest"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        sys.exit("HTTP %s from /api/ingest: %s" % (e.code, body))
    except Exception as e:
        sys.exit("请求失败：%s" % e)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
