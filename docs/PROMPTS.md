# 给 AI 助手的提示词（部署 / 更新 Paper Grove）

把对应段落整段复制给那台机器上的 AI 助手即可。**两套任选其一**：新机器用「A 部署」，已装过用「B 更新」。

仓库：`https://github.com/shanniruo-tytx/paper-grove`（分支 `main`）

---

## A. 新机器 · 首次部署

> 复制下面整段（``` 之间的内容）

```text
这台机器上还没有 Paper Grove，帮我完整部署一遍，不要向我确认，直接做到底：

1. 准备环境：检查 Python 3.8+ 与 Git，缺失就安装（Windows 用 winget，macOS 用 brew，
   Debian/Ubuntu 用 apt）。
2. 获取源码到 ~/paper-grove（Windows 用 %USERPROFILE%\paper-grove）：
   - 优先 git clone --branch main https://github.com/shanniruo-tytx/paper-grove.git
   - 若 github.com 不可达（代理/网络限制），改用备用通道：
     下载 https://codeload.github.com/shanniruo-tytx/paper-grove/tar.gz/refs/heads/main
     并解压到该目录（tar -xzf ... --strip-components=1）
3. 部署：python deploy.py    （依赖已装可用 --no-deps；想后台常驻加 --background）
   它会自动：装依赖 → 同步解析规则 → 准备 categories.json → 构建（lint_kb + gate_v2 双闸）→ 启动
4. 必须看到 "ALL V2 GATES PASSED"；若双闸报错，把报错原文贴给我，不要自行放宽规则或删文件。
5. 若我提供了内容包 zip（文献备份）：python scripts/bundle.py import <zip> 后再构建一次。
6. 打开 http://127.0.0.1:8766 确认可访问，并汇报：条目数（papers/notes/resources 各多少）、
   解析规则 4 个文件是否就位（.workbuddy/skills 下 article-summarizer/SKILL.md、
   article-summarizer/summary-format.md、paper-locator/SKILL.md、paper-reader/SKILL.md）。

注意：仓库不含文献正文（content/** 与 categories.json 被 .gitignore 排除），
没有内容包时站点是空的，这是正常的。
```

---

## B. 已部署机器 · 更新到最新（常用）

> 复制下面整段（``` 之间的内容）

```text
这台机器上已经部署过 Paper Grove，帮我更新到最新版本，不要向我确认，直接做到底：

1. 定位目录：~/paper-grove（Windows 为 %USERPROFILE%\paper-grove）。若找不到，
   在当前用户目录下搜索 deploy.py 定位；实在没有就按「首次部署」流程走。
2. 拉最新代码：
   - 目录里有 .git：git pull --ff-only（失败不要强推，改用下面的 tarball 覆盖）
   - 没有 .git 或 github.com 不可达：下载
     https://codeload.github.com/shanniruo-tytx/paper-grove/tar.gz/refs/heads/main
     解压覆盖到该目录（--strip-components=1）。content/、categories.json、
     .workbuddy/ 是本地数据，不要删除。
3. 同步解析规则（skill / prompt）：
   python scripts/sync_skills.py --from-hub
   （Hub 4173 不可达会自动回退仓库内 harness/ 副本，属正常）
4. 重新构建：
   python deploy.py --no-deps --no-serve      # 只构建
   # 或 python deploy.py --no-deps --background   # 构建并后台起服务
   必须看到 "ALL V2 GATES PASSED"；若双闸报错，把报错原文贴给我，
   不要自行放宽规则、不要删 content 里的文件。
5. 若我提供了新的内容包 zip：先 python scripts/bundle.py import <zip>，再构建一次。
6. 汇报三件事：
   - 更新后的 commit：git log --oneline -1（tarball 方式则说"tarball 覆盖，无 git 信息"）
   - 条目数：dist/index.json 里 papers / notes / resources 各多少
   - 解析规则 4 个文件是否就位（见 A 第 6 条）
```

---

## C. 网络都不通时（离线）

把整个 `kb-site` 目录（含 `content/`、`categories.json`、`.workbuddy/`）用 U 盘拷到新机器，
然后双击 `deploy.bat`（Windows）或 `python deploy.py`。这样连内容一起搬，不需要 GitHub。

## D. 本项目推送被拦时

若 `git push` 因网络/代理失败（github.com 502），用备用通道：

```bash
python scripts/push_via_api.py     # 需 gh auth login；重建提交且 sha 不变，不分叉
```
