#!/usr/bin/env bash
# Paper Grove - 新机器一键引导脚本（macOS / Linux）
#
# 用法（无需预先安装任何东西）：
#   curl -fsSL https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.sh | bash
#
# 带参数：
#   curl -fsSL <上面的 URL> | bash -s -- --dir ~/kb --port 9000 --background
#
# 做什么：
#   1) 找 Python 3.8+（没有就尝试 apt / brew 装）
#   2) 找 Git（没有就尝试装）
#   3) clone 仓库（已存在则 fast-forward 更新）
#   4) 跑 deploy.py（装依赖 → 准备 categories.json → 构建含双闸 → 启动）
set -euo pipefail

DIR="${HOME}/paper-grove"
REPO="https://github.com/shanniruo-tytx/paper-grove.git"
BRANCH="main"
PORT="8766"
NO_SERVE=0
BACKGROUND=0
NO_DEPS=0
BUNDLE=""   # 内容包 zip 路径或 URL（content/** 与 categories.json 不入库，靠它迁移）
PYTHON_BIN=""  # 显式指定 python（已装但不在 PATH 时用）

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)        DIR="$2"; shift 2 ;;
    --repo)       REPO="$2"; shift 2 ;;
    --branch)     BRANCH="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    --no-serve)   NO_SERVE=1; shift ;;
    --background) BACKGROUND=1; shift ;;
    --no-deps)    NO_DEPS=1; shift ;;
    --bundle)     BUNDLE="$2"; shift 2 ;;
    --python)     PYTHON_BIN="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

info() { printf '\033[36m==> %s\033[0m\n' "$1"; }
good() { printf '    \033[32m[ok]\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m[!]\033[0m %s\n' "$1"; }
bad()  { printf '    \033[31m[x]\033[0m %s\n' "$1"; }

echo
echo "============================================================"
echo " Paper Grove - 新机器一键部署"
echo "============================================================"
echo

# ---------- 1. Python ----------
info "[1/4] 检查 Python 3.8+"
PY=""
if [[ -n "$PYTHON_BIN" ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then bad "指定的 python 不可执行：$PYTHON_BIN"; exit 1; fi
  ver="$("$PYTHON_BIN" -c 'import sys;print(sys.version_info[0]*1000+sys.version_info[1])' 2>/dev/null || true)"
  if [[ -z "$ver" ]] || (( ver < 3008 )); then bad "python 版本过低（需 3.8+）：$PYTHON_BIN"; exit 1; fi
  PY="$PYTHON_BIN"
  good "使用显式 python：$PY"
fi
if [[ -z "$PY" ]]; then
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys;print(sys.version_info[0]*1000+sys.version_info[1])' 2>/dev/null || true)"
      if [[ -n "$ver" ]] && (( ver >= 3008 )); then PY="$cand"; break; fi
    fi
  done
fi

if [[ -z "$PY" ]]; then
  warn "未找到 Python 3.8+，尝试自动安装…"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip
  elif command -v brew >/dev/null 2>&1; then
    brew install python@3.12
  fi
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys;print(sys.version_info[0]*1000+sys.version_info[1])' 2>/dev/null || true)"
      if [[ -n "$ver" ]] && (( ver >= 3008 )); then PY="$cand"; break; fi
    fi
  done
fi

if [[ -z "$PY" ]]; then
  bad "仍然找不到 Python 3.8+，请手动安装后重跑：https://www.python.org/downloads/"
  exit 1
fi
good "Python: $PY $("$PY" --version 2>&1)"

# ---------- 2. Git ----------
info "[2/4] 检查 Git"
if ! command -v git >/dev/null 2>&1; then
  warn "未找到 Git，尝试自动安装…"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y git
  elif command -v brew >/dev/null 2>&1; then
    brew install git
  fi
fi
if ! command -v git >/dev/null 2>&1; then
  bad "Git 不可用，请手动安装后重跑：https://git-scm.com/"
  exit 1
fi
good "Git 就绪"

# ---------- 3. Clone / update ----------
info "[3/4] 获取源码 → $DIR"
# 备用通道：部分网络屏蔽 github.com 但放行 codeload.github.com
if [[ "$REPO" =~ github\.com[:/]+([^/]+)/([^/.]+) ]]; then
  TARBALL="https://codeload.github.com/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/tar.gz/refs/heads/${BRANCH}"
else
  TARBALL=""
fi

get_via_tarball() {
  local dest="$1"
  [[ -n "$TARBALL" ]] || { bad "无法从 $REPO 推导 tarball 地址"; return 1; }
  command -v tar >/dev/null 2>&1 || { bad "tar 不可用"; return 1; }
  local tmp="${TMPDIR:-/tmp}/pg-$$.tar.gz"
  info "下载源码 tarball（codeload）…"
  curl -fsSL "$TARBALL" -o "$tmp" || { bad "tarball 下载失败"; return 1; }
  mkdir -p "$dest"
  tar -xzf "$tmp" -C "$dest" --strip-components=1 || { bad "解压失败"; return 1; }
  rm -f "$tmp"
  good "已从 tarball 解出源码"
}

if [[ -d "$DIR/.git" ]]; then
  good "已存在仓库，fast-forward 更新…"
  git -C "$DIR" pull --ff-only || warn "git pull 失败（本地有提交？），保留现有副本"
else
  if ! git clone --branch "$BRANCH" "$REPO" "$DIR" 2>/dev/null; then
    warn "git clone 失败（github.com 不可达？）→ 改用 tarball 通道"
    rm -rf "$DIR"
    get_via_tarball "$DIR" || { bad "无法获取源码，请手动拷贝目录"; exit 1; }
  else
    good "clone 完成"
  fi
fi

# ---------- 3.5 内容包（可选）----------
# content/** 与 categories.json 被 .gitignore 排除（个人数据），
# 新 clone 是空站，用 --bundle 把文献搬过来。
if [[ -n "$BUNDLE" ]]; then
  info "[3.5/4] 导入内容包"
  ZIP="$BUNDLE"
  if [[ "$BUNDLE" =~ ^https?:// ]]; then
    ZIP="${TMPDIR:-/tmp}/pg-bundle-$(basename "$BUNDLE")"
    curl -fsSL "$BUNDLE" -o "$ZIP" || { bad "内容包下载失败"; exit 1; }
  fi
  [[ -f "$ZIP" ]] || { bad "找不到内容包：$ZIP"; exit 1; }
  "$PY" "$DIR/scripts/bundle.py" import "$ZIP" --root "$DIR" || { bad "内容包导入失败"; exit 1; }
  good "内容导入完成"
fi

# ---------- 4. Deploy ----------
info "[4/4] 运行 deploy.py"
cd "$DIR"
ARGS=("deploy.py" "--port" "$PORT")
(( NO_SERVE ))   && ARGS+=("--no-serve")
(( BACKGROUND )) && ARGS+=("--background")
(( NO_DEPS ))    && ARGS+=("--no-deps")

"$PY" "${ARGS[@]}"
