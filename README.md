# Paper Grove

把学术论文变成**双层可读笔记**的本地知识库站点：每篇论文同时挂载「深度拆解」（专业 + 白话双栏）与「白话解读」（速读双栏 + 术语表），并自带分类树、标签、检索、分页与目录导航。纯静态生成 + 本地轻后端，零云依赖、零 AI 调用。

> 本仓库**只含框架代码**，不含任何个人论文与分类数据（论文正文、笔记、`categories.json`、个人技能目录等已被 `.gitignore` 排除）。clone 下来是空架子，按下方「内容规范」填入你自己的文献即可。

---

## 1. 特性

- **双层笔记渲染**：深度拆解（`## #0`–`## #9` 十节 + 每节【专业描述】/【白话解释】双栏）、白话解读（六节速读双栏 + 末尾专业术语文白对照表）。
- **分类树**：多级分类，可挂论文；论文必须落在分类树内，笔记/拆解附属某篇论文。
- **文献库**：卡片网格、按分类/年份/标签/全文检索过滤、排序、**分页**（每页 10/20/50/100 可调，含首页/尾页/跳转）。
- **条目详情**：自动目录（h2/h3）、frontmatter 元信息、双栏对照排版。
- **本地编辑后端**：`server.py` 提供分类树管理与条目增删改的 HTTP API（分类创建/改名/删除、条目创建/更新/删除、RDF/Zotero 导入触发重建）。

---

## 2. 快速部署（3 步）

环境要求：**Python 3.8+**（仅用到标准库 + 一个 markdown 库）。

```bash
# 1) 克隆
git clone https://github.com/shanniruo-tytx/paper-grove.git
cd paper-grove

# 2) 安装依赖
pip install -r requirements.txt
#   markdown 为必装；PyYAML 为可选（缺失时 frontmatter 改用内置兜底解析）

# 3) 准备分类树（可选但推荐）：
#    仓库不带你的 categories.json，请从示例复制一份再改
cp categories.example.json categories.json

# 4) 生成静态站点
python build.py
#   -> 输出到 dist/，打印 "built N entries -> dist"

# 5) 启动本地站点
python server.py
#   -> 打开 http://localhost:8766
```

> 端口可用环境变量覆盖：`PORT=9000 python server.py`。

---

## 3. 目录结构

```
paper-grove/
├── build.py              # 构建：扫描 content/ -> 生成 dist/ 静态站点
├── server.py             # 本地后端（ThreadingHTTPServer）+ 分类/条目管理 API
├── gate_v2.py            # 语义校验（双栏对齐 / 白话价值等 Gate）
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

`dist/`、`_papers_archive/`、`categories.json`、`content/papers/*.md`、`content/notes/*.md` 等均为**本地生成或个人数据**，不入库。

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

> 这两套格式由 `paper-reader` 技能（拆解）与 `paper-importer` 流程（导入归档）生成；本仓库不含这些技能，它们属于个人 `.workbuddy/skills`，不在版本库中。

---

## 6. 日常使用

| 操作 | 命令 |
| --- | --- |
| 重新生成站点 | `python build.py` |
| 本地预览 | `python server.py` → http://localhost:8766 |
| 改完内容后刷新 | 在站点里点重建，或终端再跑一次 `python build.py` |
| 加一篇论文 | 往 `content/papers/` 丢一个 `<id>_论文.md` |
| 加一条笔记 | 往 `content/notes/` 丢 `<id>_论文拆解.md`（设 `parent_paper`） |
| 新建/调整分类 | 编辑 `categories.json`（数组：`{id, name, parent}`）|

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
