#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper Grove 一键部署。

把「装依赖 → 准备分类树 → 构建（含双闸校验）→ 启动站点」串成一条命令：

    python deploy.py                 # 装依赖 + 构建 + 前台启动 http://localhost:8766
    python deploy.py --no-deps       # 跳过装依赖（已装过用它，最快）
    python deploy.py --background    # 后台常驻启动，脚本立即返回
    python deploy.py --no-serve      # 只构建不启动（CI / 只想生成 dist 时用）
    python deploy.py --no-build      # 只启动不重建
    python deploy.py --port 9000     # 换端口（等价 PORT=9000）

构建阶段会跑 build.py 内的两道硬闸（scripts/lint_kb.py + gate_v2.py），
任一不过即中断并返回非零码，不会产出半成品站点。
"""
import os
import sys
import subprocess
import argparse
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def step(n, msg):
    print("\n[%d/4] %s" % (n, msg))


def ok(msg):
    print("      ✓ %s" % msg)


def fail(msg):
    print("      ✗ %s" % msg, file=sys.stderr)
    sys.exit(1)


def module_available(name):
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="Paper Grove 一键部署")
    ap.add_argument("--port", default=os.environ.get("PORT", "8766"), help="站点端口（默认 8766）")
    ap.add_argument("--no-deps", action="store_true", help="跳过依赖安装")
    ap.add_argument("--no-build", action="store_true", help="跳过构建")
    ap.add_argument("--no-serve", action="store_true", help="只构建/装依赖，不启动站点")
    ap.add_argument("--background", action="store_true", help="后台常驻启动（脚本立即返回）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    print("=" * 60)
    print("Paper Grove · 一键部署")
    print("=" * 60)

    # ---------- 0. Python 版本 ----------
    if sys.version_info < (3, 8):
        fail("需要 Python 3.8+，当前 %s" % sys.version.split()[0])
    ok("Python %s" % sys.version.split()[0])

    # ---------- 1. 依赖 ----------
    step(1, "检查/安装依赖")
    if args.no_deps:
        ok("已指定 --no-deps，跳过")
    else:
        req = os.path.join(ROOT, "requirements.txt")
        if os.path.exists(req):
            rc = subprocess.run([PY, "-m", "pip", "install", "-r", req],
                                cwd=ROOT).returncode
            if rc != 0:
                # PyYAML 是可选的，整体失败时退回只装必装的 markdown
                print("      ! 整体安装失败，回退为只安装必选依赖 markdown")
                rc2 = subprocess.run([PY, "-m", "pip", "install", "markdown>=3.3"],
                                     cwd=ROOT).returncode
                if rc2 != 0:
                    fail("依赖安装失败，请手动执行 pip install -r requirements.txt")
            ok("依赖就绪")
        else:
            print("      ! 未找到 requirements.txt，跳过")
    # 必装校验：markdown 缺失会直接让 build.py 失败
    if not module_available("markdown"):
        fail("缺少必装依赖 markdown：pip install markdown>=3.3")

    # ---------- 2. 分类树 ----------
    step(2, "准备分类树 categories.json")
    cat = os.path.join(ROOT, "categories.json")
    example = os.path.join(ROOT, "categories.example.json")
    if os.path.exists(cat):
        ok("已存在 categories.json")
    elif os.path.exists(example):
        shutil.copyfile(example, cat)
        ok("已从 categories.example.json 复制（可自行改成你的分类树）")
    else:
        print("      ! 无 categories.json 也无示例，build.py 会回退到仅「待归类(uncat)」")

    # ---------- 3. 构建（含双闸） ----------
    if args.no_build:
        step(3, "跳过构建（--no-build）")
    else:
        step(3, "构建静态站点（lint_kb + gate_v2 双闸）")
        p = subprocess.run([PY, os.path.join(ROOT, "build.py")],
                           cwd=ROOT, capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            print(out)
            fail("构建失败（双闸未通过），已中止部署。请按上方报错修正后重跑。")
        # 只回显最后几行，避免刷屏
        tail = [l for l in out.strip().split("\n") if l.strip()][-3:]
        for l in tail:
            print("      " + l)

    # ---------- 4. 启动 ----------
    if args.no_serve:
        step(4, "跳过启动（--no-serve）")
        print("\n部署完成：静态站点已生成在 dist/")
        print("需要预览时运行：python server.py  （或 python deploy.py --no-deps --no-build）")
        return

    step(4, "启动本地站点")
    url = "http://localhost:%s" % args.port
    env = dict(os.environ)
    env["PORT"] = str(args.port)

    if args.background:
        # 后台常驻：Windows 下用 DETACHED_PROCESS 脱离父进程，父进程退出后仍在运行
        cf = 0
        if os.name == "nt":
            cf = 0x00000008  # DETACHED_PROCESS
        proc = subprocess.Popen([PY, os.path.join(ROOT, "server.py")],
                                cwd=ROOT, env=env,
                                creationflags=cf,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("      ✓ 后台已启动（PID %d）→ %s" % (proc.pid, url))
        print("      停止方式：taskkill /PID %d /F" % proc.pid)
    else:
        print("      → %s  （Ctrl+C 停止）" % url)
        if args.open:
            import webbrowser, threading
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        sys.stdout.flush()
        try:
            subprocess.run([PY, os.path.join(ROOT, "server.py")], cwd=ROOT, env=env)
        except KeyboardInterrupt:
            print("\n已停止。")

    print("\n部署完成 → %s" % url)


if __name__ == "__main__":
    main()
