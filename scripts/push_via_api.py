#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub API 精确重放本地提交（github.com 被代理/网络拦截时的备用推送通道）。

用法（需已安装并登录 gh：`gh auth login`）：
    python scripts/push_via_api.py

只在 `git push` 走不通时使用（例如代理只放行 api.github.com / codeload，
而 github.com 返回 502）。它用 Git Data API 逐个重建 commit，保证
tree / parent / author / committer / message 与本地完全一致 —— 因此
**commit sha 相同，不会造成历史分叉**。

安全措施：先把所有 commit 在远端构建出来并逐个比对 sha，全部一致才
一次性更新 refs/heads/main；任何一处不一致即中止，不留副作用。
"""
import os
import sys
import json
import base64
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER, REPO = "shanniruo-tytx", "paper-grove"
API = "https://api.github.com/repos/%s/%s" % (OWNER, REPO)


def git(*a, binary=False):
    r = subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def get_token():
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    t = r.stdout.strip()
    if not t:
        sys.exit("gh 未登录，拿不到 token")
    return t


TOKEN = get_token()


def api(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "token " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "push-via-api")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        sys.exit("API %s %s 失败: %s %s" % (method, path, e.code, body))


def main():
    base = git("rev-parse", "origin/main").strip()
    shas = git("rev-list", "--reverse", "%s..main" % base).split()
    if not shas:
        print("没有待推送的提交")
        return
    print("base(origin/main) = %s" % base[:10])
    print("待重放 %d 个提交\n" % len(shas))

    cur = base
    created = []
    ok_all = True

    for c in shas:
        head = git("show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", c).strip("\n")
        an, ae, ad, cn, ce, cd = head.split("\x00")
        raw = git("cat-file", "commit", c, binary=True)
        _h, _sep, msg = raw.partition(b"\n\n")
        msg = msg.decode("utf-8")

        parent_tree = api("GET", "/git/commits/%s" % cur)["tree"]["sha"]

        entries = []
        for line in git("diff-tree", "-r", "--no-commit-id", "--name-status", c).strip().split("\n"):
            if not line.strip():
                continue
            st, path = line.split("\t", 1)
            if st in ("A", "M", "T"):
                blob = git("cat-file", "blob", "%s:%s" % (c, path), binary=True)
                mode = git("ls-tree", c, "--", path).split()[0]
                b = api("POST", "/git/blobs", {
                    "content": base64.b64encode(blob).decode("ascii"),
                    "encoding": "base64",
                })
                entries.append({"path": path, "mode": mode, "type": "blob", "sha": b["sha"]})
            elif st == "D":
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

        tree = api("POST", "/git/trees", {"base_tree": parent_tree, "tree": entries})
        commit = api("POST", "/git/commits", {
            "message": msg,
            "tree": tree["sha"],
            "parents": [cur],
            "author": {"name": an, "email": ae, "date": ad},
            "committer": {"name": cn, "email": ce, "date": cd},
        })
        match = commit["sha"] == c
        ok_all = ok_all and match
        created.append((c, commit["sha"], match))
        print("  %s -> %s  %s  %s" % (
            c[:10], commit["sha"][:10], "SHA 一致" if match else "!! SHA 不一致",
            msg.split("\n")[0][:50]))
        cur = commit["sha"]

    if not ok_all:
        print("\n存在 SHA 不一致，已中止：未更新远端 ref（无副作用）。")
        sys.exit(1)

    res = api("PATCH", "/git/refs/heads/main", {"sha": cur})
    print("\n已更新 refs/heads/main -> %s" % res["object"]["sha"][:10])
    print("远程 main 现在与本地一致（%d 个提交）" % len(created))


if __name__ == "__main__":
    main()
