# Paper Grove

把学术论文变成**双层可读笔记**的本地知识库站点：每篇论文同时挂载「深度拆解」（专业 + 白话双栏）与「白话解读」（速读双栏 + 术语表），并自带分类树、标签、检索、分页与目录导航。纯静态生成 + 本地轻后端，零云依赖、零 AI 调用。

> 本仓库**只含框架代码**，不含任何个人论文与分类数据（论文正文、笔记、`categories.json`、个人技能目录等已被 `.gitignore` 排除）。clone 下来是空架子，按下方「内容规范」填入你自己的文献即可。

> 📐 **架构、设计理念、使用方式，以及「大模型反向代理论文解析 + 自主调接口写入」的运行模式**，详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 1. 特性

- **双层笔记渲染**：深度拆解（`## #0`–`## #9` 十节 + 每节【专业描述】/【白话解释】双栏）、白话解读（六节速读双栏 + 末尾专业术语文白对照表）。
- **分类树**：多级分类，可挂论文；论文必须落在分类树内，笔记/拆解附属某篇论文。
- **文献库**：卡片网格、按分类/年份/标签/全文检索过滤、排序、**分页**（每页 10/20/50/100 可调，含首页/尾页/跳转）。
- **条目详情**：自动目录（h2/h3）、frontmatter 元信息、双栏对照排版。
- **本地编辑后端**：`server.py` 提供分类树管理与条目增删改的 HTTP API（分类创建/改名/删除、条目创建/更新/删除、RDF/Zotero 导入触发重建）。

---

## 2. 一键部署

环境要求：**Python 3.8+**（仅用到标准库 + 一个 markdown 库）。

```bash
git clone https://github.com/shanniruo-tytx/paper-grove.git
cd paper-grove

python deploy.py          # 装依赖 → 构建（双闸校验）→ 启动 http://localhost:8766
```

一条命令串完四步：装依赖 → 准备 `categories.json`（缺失时自动从示例复制）→ `build.py` 构建（内含 `lint_kb.py` + `gate_v2.py` 双闸）→ 启动 `server.py`。

| 命令 | 作用 |
| --- | --- |
| `python deploy.py` | 完整部署并**前台**启动（Ctrl+C 停止） |
| `python deploy.py --no-deps` | 依赖已装，跳过安装（最快） |
| `python deploy.py --background` | **后台常驻**启动，脚本立即返回并打印 PID |
| `python deploy.py --no-serve` | 只构建不启动（CI / 只想产出 `dist/`） |
| `python deploy.py --no-build` | 只启动不重建 |
| `python deploy.py --port 9000 --open` | 换端口并自动开浏览器 |

Windows 双击 `deploy.bat` 等同 `python deploy.py`。

### 2.1 换一台新电脑（一条命令）

新机器上**不需要先装 Python / Git / 克隆仓库**，`scripts/bootstrap.*` 会自己搞定（缺 Python 走 winget / apt / brew 装，缺 Git 同理），然后 clone 并调用 `deploy.py`。

**Windows（PowerShell，一行）**

```powershell
irm https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.ps1 | iex
```

**macOS / Linux（一行）**

```bash
curl -fsSL https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.sh | bash
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `-Dir D:\kb` / `--dir ~/kb` | 装到指定目录（默认 `~/paper-grove`） |
| `-Bundle <zip 或 URL>` / `--bundle ...` | **连文献一起搬**（见下） |
| `-Port 9000` / `--port 9000` | 换端口 |
| `-Background` / `--background` | 部署后后台常驻 |
| `-Python <路径>` / `--python <路径>` | 已装 Python 但不在 PATH 时显式指定 |
| `-NoServe` / `--no-serve` | 只构建不启动 |

> 无参数直接跑也能用，只是站点是**空的**——因为 `content/**` 与 `categories.json` 属于个人数据，被 `.gitignore` 排除，仓库里只有程序壳。

**把文献一起带过去**：先在旧机器打包，再在新机器导入。

```bash
# 旧机器：导出内容包（content/*.md + categories.json，约 1.8 MB）
python scripts/bundle.py export
# → _bundle/paper-grove-content-<时间戳>.zip

# 新机器：引导时一步到位
powershell -File scripts/bootstrap.ps1 -Bundle D:\backup\paper-grove-content-20260919.zip
# 或已部署完再补：python scripts/bundle.py import <zip>
```

**解析规则（skill / prompt）不会丢**：`harness/article-summarizer/` 是**入库**的规范副本（skills：`article-summarizer` / `paper-locator` / `paper-reader`；prompts：`summary-format`），而真正被 agent 读取的 `.workbuddy/skills/` 被 `.gitignore` 排除。`deploy.py` 第 2 步会自动把前者灌到后者，所以新机器部署完即刻按同一套规则解析。

```bash
python scripts/sync_skills.py            # 仓库副本 -> 执行副本（离线可用）
python scripts/sync_skills.py --from-hub # 优先从 Hub(4173) 拉，不可达则回退
python scripts/sync_skills.py --to-repo  # 反向：本地改完写回仓库，便于提交
```

> 规则改动的唯一规范源仍是 Hub（4173）。在 Hub 改完 → `--from-hub` 拉到执行副本 → 需要沉淀进仓库时再 `--to-repo` 并提交。

<details>
<summary>手动分步（等价上面那条命令，仅在你不想用脚本时）</summary>

```bash
pip install -r requirements.txt
cp categories.example.json categories.json   # 可选，无则全部落在「待归类」
python build.py                              # -> dist/，打印 built N entries
python server.py                             # -> http://localhost:8766
```

</details>

> 端口可用环境变量覆盖：`PORT=9000 python server.py`。
> 构建被双闸拦下时 `deploy.py` 会原样打印报错并**中止**，不会产出半成品站点。

---

## 3. 目录结构

```
paper-grove/
├── deploy.py             # 【一键部署】装依赖 → 构建（双闸）→ 启动站点
├── deploy.bat            # Windows 双击版入口（等同 python deploy.py）
├── build.py              # 构建：扫描 content/ -> 生成 dist/ 静态站点（开头跑第 1 闸）
├── server.py             # 本地后端（ThreadingHTTPServer）+ 分类/条目/导入 API
├── ingest.py             # 接口化导入助手：本地 md -> POST /api/ingest -> 落库+构建
├── gate_v2.py            # 第 2 闸：v2 论文挂载完整性 + 拆解↔白话 指标一致性
├── scripts/lint_kb.py    # 第 1 闸：kind 契约 / 资源隔离 / 防模板串流 / 双栏格式
├── scripts/bootstrap.ps1 # 【换机器】Windows 一键引导：装 Python/Git → clone → 部署
├── scripts/bootstrap.sh  # 【换机器】macOS/Linux 一键引导
├── scripts/bundle.py     # 内容包 export/import：把文献搬到新机器
├── scripts/sync_skills.py # 解析规则同步：harness/（或 Hub）-> .workbuddy/skills
├── harness/              # 【入库】解析规则规范副本（article-summarizer 的 skill/prompt）
├── paper_pipeline/       # 管线模块（解析、frontmatter 校验、归档等）
├── import_rdf.py         # 从 Zotero 导出的 .rdf 批量导入
├── import_zotero.py      # Zotero 导入辅助
├── reclassify.py         # 重分类工具
├── migrate.py            # 旧数据迁移工具
├── assets/               # 前端：app.js / style.css / marked.min.js（已内置）
├── templates/            # 站点模板：index.html / entry.html
├── content/
│   ├── papers/           # 【你的数据】论文条目 *.md（仓库不含，见 .gitignore）
│   └── notes/            # 【你的数据】拆解/白话笔记 *.md（仓库不含）
├── categories.example.json  # 分类树示例（仅 uncat + 一个示例分类，零个人数据）
├── .gitignore            # 已排除个人数据
└── requirements.txt
```

`dist/`、`_papers_archive/`、`categories.json`、`content/papers/*.md`、`content/notes/*.md`、`content/resources/*.md` 等均为**本地生成或个人数据**，不入库。

---

## 4. 内容规范

### 4.1 论文条目 `content/papers/<id>_论文.md`

```yaml
---
title: 论文英文/中文标题
type: paper            # 或 note（见 4.2）
category: example_cat  # 必须存在于 categories.json；论文必须落在分类树内
journal: Nature Methods
date: 2026-05-12
source: https://doi.org/10.xxxx/xxxxx
tags: [单细胞, 图神经网络]
summary: 一句话摘要
doi: 10.xxxx/xxxxx
pdf: 无                 # 或 PDF 链接
---
```

### 4.2 笔记 `content/notes/<id>_论文拆解.md` / `<id>_论文白话解读.md`

```yaml
---
title: 标题
kind: note              # 固定
parent_paper: papers_<id>_论文   # 精确对应论文条目 slug（前缀 papers_ + 文件名去 .md）
type: note
---
```

正文约定：

- 正文**不要**写与标题重复的 `# Title`（渲染时自动去除）。
- 正文**不要**写 `[TOC]`（前端自动生成目录）。
- 正文从 `## #0` 开始；`#0` 区块为松散键值对，前端自动渲染为表格。

### 4.3 知识资料 `content/resources/<id>.md`（只在「知识库」显示，不进文献库）

非论文材料（综述 / 论坛帖 / 工具或产品介绍 / 访谈 / 新闻 / 观点评论）走这里，是**独立条目**：

```yaml
---
title: 标题
kind: resource
doc_type: 技术博客 / 综述 / 论坛帖 / 官方文档 / 文本 / 新闻
category: uncat          # 固定 uncat：资源不参与文献库分类树
source: 原文链接
journal: 出处名（公众号/站点名）
authors: [作者或机构]
date: 2026-05-12
created: 2026-05-12 10:30
tags: [领域, 方法]
summary: 摘要长文
一句话概括: ≤140 字电梯演讲（是什么/解决什么问题/为什么值得记）
---
```

隔离铁律（`scripts/lint_kb.py` 强制，违反即 build 失败）：`kind` 必须精确 `resource`、**绝不写 `parent_paper`**、`category` 固定 `uncat`。这样资源物理上不可能进文献库。

---

## 5. 双层笔记格式

**深度拆解**（`*_论文拆解.md`）：`## #0` 基本信息表 → `## #1`–`## #9` 十节，每节含：

```
## #1. 研究背景与问题
**【专业描述】** ……（准确、术语化）
**【白话解释】** ……（展开、类比、去术语）
```

`#0` 必须为表格形式（`| 字段 | 值 |`），用于基本信息速览。

**白话解读**（`*_论文白话解读.md`）：六节速读，每节双栏（【专业描述】+【白话解释】），文末附「专业术语文白对照表」。

> 这两套格式由 `paper-reader` 技能（拆解）与 `article-summarizer` harness（统一入口：先判论文/非论文，再分流导入）生成；本仓库不含这些技能，它们属于个人 `.workbuddy/skills` 与本地 Harness Hub，不在版本库中。

---

## 6. 日常使用

| 操作 | 命令 |
| --- | --- |
| **一键部署** | `python deploy.py` |
| 重新生成站点 | `python build.py` |
| 本地预览 | `python server.py` → http://localhost:8766 |
| 改完内容后刷新 | 在站点里点「⟳ 刷新」，或再跑一次 `python build.py` |
| 加一篇论文 | 往 `content/papers/` 丢一个 `<id>_论文.md` |
| 加一条笔记 | 往 `content/notes/` 丢 `<id>_论文拆解.md`（设 `parent_paper`） |
| 新建/调整分类 | 编辑 `categories.json`（数组：`{id, name, parent}`）|
| **接口化导入**（agent 用） | `python ingest.py "C:/tmp/x.md@content/papers/x_论文.md"` |
| **接口化重建** | `curl -X POST http://127.0.0.1:8766/api/build` |

### 6.1 接口化落库（让 agent 不直接碰 `content/`）

`content/` 目录只由服务端经接口持有——agent 生成好 markdown 后 POST 给服务端，由服务端原子写盘并自动跑双闸。这样避免多处直写导致契约被绕过。

```bash
# 1) 把生成好的 markdown 先写到任意临时目录
# 2) 用 ingest.py 投给服务端（"本地文件@目标content路径"）
python ingest.py \
  "C:/tmp/x_papers.md@content/papers/x_论文.md" \
  "C:/tmp/x_deep.md@content/notes/x_论文拆解.md" \
  "C:/tmp/x_explain.md@content/notes/x_论文白话解读.md"
```

- 等价于 `POST /api/ingest`，body：`{"files":[{"path":"content/.../x.md","content":"<完整 md 含 frontmatter>"}],"build":true}`。
- 返回 `{"written":[...], "build":{"ok":true,"exit":0,"log_tail":"..."}}`；`build.ok=false` 时读 `log_tail` 定位违规（缺 `一句话概括` / 缺双栏 / v2 缺白话笔记 / 指标冲突），修正后**重投同一接口**即可，已写文件不会丢。
- 接口只允许 `content/{papers,notes,resources}/*.md`，禁目录穿越；写盘用 temp+原子替换。CORS 已开，可跨域调用。
- 只重建不写文件：`POST /api/build`。

---

## 7. 部署到公网（可选）

站点本质是静态文件（`dist/`）。可选方案：

- **静态托管**：把 `dist/` 拖到任意静态托管（GitHub Pages / Netlify / CloudStudio 等）。注意 `server.py` 的管理 API 不在静态托管里，分类/条目管理需在本机 `server.py` 完成后再构建上传。
- **自带后端**：在有 Python 的服务器上 `python server.py`，用 Nginx/Caddy 反向代理 `8766` 端口。

---

## 8. 常见问题

- **`ImportError: No module named 'markdown'`**：没装依赖，跑 `pip install -r requirements.txt`。
- **没有 `categories.json` 能跑吗？**：能。`build.py` 在缺失时自动回退到仅 `待归类(uncat)`，论文都会进「待归类」。推荐从 `categories.example.json` 复制后改成你自己的树。
- **笔记没出现在论文详情里？**：检查 `parent_paper` 是否精确等于 `papers_<论文文件名去 .md>`（注意前缀 `papers_`，且论文文件名**不带** `_论文` 之外多余后缀）。
- **目录（TOC）不显示？**：确认正文用 `## #N.` 二级标题（h2）；用单 `#` 会变成 h1，前端目录只抓 h2/h3。
- **改了内容不刷新？**：跑一次 `python build.py` 重建 `dist/`。

---

## License

框架代码可自由用于个人/学术知识库搭建。
