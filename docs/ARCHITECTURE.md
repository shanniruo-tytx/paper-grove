# Paper Grove · 架构与设计说明

> 本文档说明 `kb-site` 知识库站点的**整体架构**、**设计理念**、**使用方式**，以及**「让大模型反向代理论文解析任务、并自主调接口写入」**的运行模式。
> 配套代码见仓库根目录：`build.py` / `server.py` / `gate_v2.py` / `scripts/lint_kb.py` / `paper_pipeline/`，以及 `.workbuddy/skills/` 下的技能 harness。

---

## 0. TL;DR（一句话）

`kb-site` 是一个**「文件即数据库 + 构建即发布」**的本地知识库：所有内容都是 `content/` 下的 Markdown 文件，由 `build.py` 渲染成静态站点 `dist/`，由 `server.py` 本地托管并提供管理/写入 API；**作者（无论是人还是大模型 agent）直接写 Markdown 文件（或调写入接口），构建脚本用两道硬闸保证内容契约不被破坏**。

所谓「大模型反向代理」，是指：**解析论文这件事不再由某个常驻后台程序拿着 apikey 自动跑，而是由大模型 agent 本人坐在请求链路上**——读链接、判路线、定位原文、拆解读写、调写入接口落库、再触发构建校验。apikey 只存在于 agent 会话里，永不下放到常驻服务端。

---

## 1. 整体架构

### 1.1 组件与数据流

```
                         ┌──────────────────────────────────────────────┐
                         │              作者层 (Agent / 人)              │
                         │  article-summarizer → paper-locator →          │
                         │  paper-reader  (技能 harness，产出 Markdown)   │
                         └───────────────┬──────────────────────────────┘
                                         │  写入接口 (Write Interface)
                          ┌──────────────┴───────────────────────────────┐
                          │  (A) 直接写文件 content/{papers,notes,resources}/*.md   │
                          │  (B) 或 POST /api/entry/create  (server.py 写入接口)    │
                          └──────────────┬───────────────────────────────┘
                                         │
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │  content/  (单一事实源：Markdown + frontmatter) │
                    │   papers/  notes/  resources/                  │
                    └───────────────┬──────────────────────────────┘
                                    │  build.py 扫描 + 渲染 + 校验
                                    ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ 两道硬闸（任一失败 → build 直接 sys.exit，dist 不 emit）            │
        │   1) scripts/lint_kb.py   内容契约 / 资源隔离 / 防模板串流 / 双栏格式 │
        │   2) gate_v2.py           v2 论文挂载完整性 + 拆解↔白话 指标一致性     │
        └───────────────┬──────────────────────────────────────────────┘
                        │  通过 → 生成 dist/
                        ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  dist/  (静态站点)                                              │
        │    index.json   (前端读取的全部条目 + 分类树)                      │
        │    *.html       (每篇条目的详情页，双栏渲染)                       │
        │    assets/      (app.js / style.css / marked.min.js)            │
        └───────────────┬──────────────────────────────────────────────┘
                        │  server.py 托管 + 管理 API
                        ▼
                  http://localhost:8766  (本地预览 / 公网反代)
```

### 1.2 各组件职责

| 组件 | 角色 | 是否含 AI / apikey |
|---|---|---|
| `content/*.md` | 唯一事实源；frontmatter 描述元数据，正文是双栏 Markdown | 否 |
| `build.py` | 扫描 `content/` → 解析 frontmatter（yaml 优先，失败回落行级兜底）→ 渲染 → 写 `dist/` → **触发两道闸** | 否 |
| `dist/` | 构建产物（静态站点）；`index.json` 是前端数据总线 | 否 |
| `server.py` | 本地 HTTPServer；托管 `dist/`；提供分类/条目管理 API 与**写入接口** `/api/entry/create` | 否（无 apikey） |
| `scripts/lint_kb.py` | 第 1 道闸：kind 契约、resources 隔离、防模板串流、notes 双栏格式 | 否 |
| `gate_v2.py` | 第 2 道闸：对 `pipeline_version: paper-pipeline-v2` 的论文强制「拆解+白话」双笔记齐全且 parent 匹配、关键指标数值一致 | 否 |
| `.workbuddy/skills/*` | agent 端作者层：路线判定、原文定位、论文拆解（产出 Markdown） | **是（在 agent 会话内）** |
| `paper_pipeline/` | 确定性环节模块：身份解析/去重、Canonical 落盘、语义 Gate、staging 事务、resume | 否（只校验/持久化 agent 产出） |

> ⚠️ 关键边界：**只有「作者层（agent/人）」持有 LLM 能力**；`build.py` / `server.py` / 两个 gate / `paper_pipeline/` 全部是**确定性、无 apikey** 的代码。这保证了「解析智能」与「存储/校验」彻底解耦。

---

## 2. 设计理念

### 2.1 内容契约（kind 三分）

`content/` 下三个目录各自只放一种 `kind`，由 frontmatter 的 `kind` 字段（或 `type`）声明，并被 `lint_kb.py` 强制：

- `papers/` → `kind: paper`（顶层论文条目，必须落在分类树 `categories.json` 内）
- `notes/`  → `kind: note`（附属某篇论文的笔记，`parent_paper` 必须能解析到某 `papers_` slug）
- `resources/` → `kind: resource`（独立知识资料，**不参与文献库分类树**）

### 2.2 资源隔离（防串流）

`resources/` 是「知识库」视图的数据，与「文献库」视图（`papers/`）物理隔离。`lint_kb.py` 强制三条铁律，违反即 build 失败：

1. `kind` 必须精确为 `resource`；
2. **绝不写 `parent_paper`**（资源是独立条目，不挂靠任何论文）；
3. `category` 固定 `uncat`（资源不进分类树；写了具体分类反会被筛选隐藏）。

此外，`resources/` 正文**不得含论文拆解指纹**（`【专业描述】`/`【通俗解释】`/`论文 Story`/`作者想回答的问题`/`## #0. 原始论文识别`）——这从物理上阻止了「把论文拆解模板误用到知识资料」的串流。前端视图层再兜一道：`library` 只取 `papers()`，`knowledge` 只取 `resources()`。

### 2.3 v2 新版解析（`paper-pipeline-v2`）

一篇「新版解析」论文 = **三个文件、一个标记**：

```
content/papers/{slug}_论文.md            # kind:paper, pipeline_version: paper-pipeline-v2
content/notes/{slug}_论文拆解.md         # kind:note, note_type: paper_analysis,  【专业描述】+【通俗解释】 #0–#9
content/notes/{slug}_论文白话解读.md      # kind:note, note_type: paper_explainer, 7 节双栏 + 术语表
```

`gate_v2.py` 对带 `pipeline_version: paper-pipeline-v2` 的论文强制校验：

- `DEEP_ANALYSIS_PRESENT`（拆解笔记存在）
- `PLAIN_EXPLANATION_PRESENT`（白话解读存在）
- `PARENT_PAPER_MATCH`（两笔记 `parent_paper` == 论文 slug）
- `FRONTMATTER_VALID`
- `CONSISTENCY_GATE`（拆解与白话解读里的 Pearson/Spearman/p/F1/准确率/AUC 等关键数值必须一致，否则 FAIL）

> 白话解读笔记里**不要写**可量化指标数值，可彻底规避 `CONSISTENCY_GATE` 冲突（当前库内 7 篇 collection_229 论文即采用此策略）。

### 2.4 为什么是「文件 + 构建」而不是数据库

- **可审查**：每篇内容都是人可读的 Markdown，diff 即变更记录，无需专用客户端。
- **可复现**：`build.py` 是纯函数式（输入 `content/` → 输出 `dist/`），换机器 `python build.py` 即得同站。
- **易协作**：git 直接版本管理；作者（人/agent）只需产出 Markdown，校验交给确定性脚本。
- **无锁**：没有常驻数据库进程，写入接口只是「写文件 + 重构建」，天然并发友好。

---

## 3. 使用说明

### 3.1 本地部署（一键）

```bash
git clone https://github.com/shanniruo-tytx/paper-grove.git
cd paper-grove

python deploy.py        # 装依赖 → 准备 categories.json → 构建（双闸）→ 启动 http://localhost:8766
```

`deploy.py` 四步依次是：装依赖（失败会回退为只装必选的 `markdown`）→ `categories.json` 缺失时从示例复制 → `build.py`（内含 `lint_kb` + `gate_v2`，不过即中止、不留半成品）→ 启动 `server.py`。

常用开关：`--no-deps`（跳过装依赖）、`--background`（后台常驻，打印 PID）、`--no-serve`（只构建）、`--no-build`（只启动）、`--port 9000`、`--open`。Windows 双击 `deploy.bat` 等效。

#### 3.1.1 换机器部署（`scripts/bootstrap.*`）

新机器上不必预装 Python / Git，引导脚本会自己装（winget / apt / brew），然后 clone 并转交 `deploy.py`：

```powershell
# Windows
irm https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.sh | bash
```

因为 `content/**` 与 `categories.json` 不入库，裸跑得到的是空站；要连文献一起迁移用内容包：旧机器 `python scripts/bundle.py export` 产出 zip，新机器 `-Bundle <zip>`（或事后 `python scripts/bundle.py import <zip>`）。

<details>
<summary>等价的分步命令</summary>

```bash
pip install -r requirements.txt
cp categories.example.json categories.json
python build.py
python server.py        # -> http://localhost:8766  (PORT 可环境变量覆盖)
```

</details>

### 3.2 手动加一篇

- **论文**：往 `content/papers/` 丢 `{英文简称}_论文.md`（frontmatter 见 `README.md` 4.1）。
- **笔记**：往 `content/notes/` 丢 `{简称}_论文拆解.md` / `{简称}_论文白话解读.md`，设 `parent_paper: papers_{论文文件名去 .md}`。
- **知识资料**：往 `content/resources/` 丢 `{短id}.md`，`kind: resource`、`category: uncat`、不写 `parent_paper`。
- 改完跑一次 `python build.py` 重建（会被两道闸校验）。

### 3.3 通过技能 harness 加（agent 驱动，推荐）

1. 把链接/文本交给 agent；
2. agent 用 `article-summarizer` 先**判定路线**（PAPER / RESOURCE / AMBIGUOUS→默认 RESOURCE）；
3. PAPER 路线：调 `paper-locator` 定位原文 → 调 `paper-reader` 产出 `#0–#9` 双栏拆解 → 写 `papers/` + 两篇 `notes/`；
4. RESOURCE 路线：按 `summary-format.md` 总结 → 写 `resources/`；
5. 跑 `build.py` 校验，并核对隔离（资源只在知识库、不进文献库）。

---

## 4. 大模型「反向代理」论文解析 + 自主调接口写入

### 4.1 两种范式对比

| 维度 | ❌ 旧范式：程序触发 apikey | ✅ 反向代理范式：agent 坐在链路里 |
|---|---|---|
| 谁持有 LLM apikey | 常驻后台服务（server/apikey 写死在配置） | **仅 agent 会话**（用完即焚，不下放） |
| 解析任务由谁发起 | 后台程序定时/Webhook 触发「调 LLM 解析」 | agent 收到用户链接后**自己**解读、拆解 |
| 写入由谁触发 | 程序解析完再「调写入接口」落库 | agent **自己**调写入接口（文件或 HTTP）落库 |
| 纠错/批判能力 | 无（程序只做格式转发） | 有（agent 可对照原文、标注夸大、发现冲突、自我校验） |
| 编排脆弱性 | 高（解析失败/格式漂移→脏数据入库） | 低（agent 在环，gate 兜底拦截） |
| 审计 | 黑盒（服务内部跑） | 透明（agent 每步可读、可追溯、可 diff） |
| 部署复杂度 | 需管理密钥、服务可用性与重试 | 仅需「会写文件的 agent + 一个无密钥的存储端」 |

> 旧范式的问题不是「用了 LLM」，而是**把 LLM 当成无状态函数、把 apikey 塞进常驻服务、把编排写成脆弱脚本**。反向代理范式让 LLM 重新成为「会思考的编排者」，而存储端退化成一个**无状态的写入接口**。

### 4.2 反向代理范式的具体形态

```
用户: "这篇微信贴 / 这个 arXiv 链接，帮我拆一下"
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │  Agent（持有 apikey，仅在本会话）              │
   │   1. WebFetch / 原生连接器  读取源文本          │
   │   2. article-summarizer      判定 PAPER/RESOURCE│
   │   3. paper-locator          定位原始论文(若需)  │
   │   4. paper-reader           产出 #0–#9 双栏拆解  │
   │   5. 组装 Markdown(frontmatter+正文)            │
   │   6. 调 写入接口 ──────────────┐                │
   │   7. 调 build 触发两道闸校验 ←─┘ (回环自检)      │
   └─────────────────────────────────────────────┘
                        │
                        ▼
              写入接口（见 4.3）→ content/ → build → dist/
```

agent 不是「把活扔给后台程序」，而是**亲自完成解析、亲自落库、亲自校验**。后台只有「存储 + 校验」，没有「智能」。

### 4.3 写入接口（Write Interface）的两种实现

「自主调接口写入」里的「接口」可以是以下任一种，二者契约一致（输入都是结构化 frontmatter + Markdown 正文，输出都是落盘 + 重建）：

#### 4.3.1 文件接口（零依赖，手动编辑时用）

agent 直接用写文件能力把 Markdown 落到 `content/{papers,notes,resources}/`——**文件系统本身就是写入接口**，无需起服务。

> 📌 **2026-09-13 起，技能 harness 的默认落库方式已切到 4.3.3 的 `/api/ingest`**：`article-summarizer` 的「步骤 5」改为「先写临时目录 → 调 `/api/ingest` → 读 `build.ok` 修正重投」。理由是让 `content/` 只由服务端经接口持有，避免多处直写绕过契约。文件接口仍保留给人工直接编辑的场景。

```text
content/papers/cellvoyager_论文.md          # kind:paper, pipeline_version: paper-pipeline-v2
content/notes/cellvoyager_论文拆解.md        # kind:note, note_type: paper_analysis, parent_paper: papers_cellvoyager_论文
content/notes/cellvoyager_论文白话解读.md     # kind:note, note_type: paper_explainer, parent_paper: papers_cellvoyager_论文
content/resources/cell_reference_mapping_weixin.md   # kind:resource, category:uncat
```

#### 4.3.2 HTTP 接口（`server.py` 的 `/api/entry/create`，已支持 paper/note/resource + 显式 slug）

当 agent 与被管站点不在同一文件系统（例如远程托管、或希望写入与文件系统解耦）时，调本地后端的写入 API。请求体：

```json
{
  "kind": "resource",                 // paper | note | resource
  "slug": "resources_cell_reference_mapping_weixin",  // 可选；不填则按标题自动生成 *_{kind}_manual_{stamp}
  "title": "Cell 封神！单细胞未来 5 年研究指南",
  "body": "## #0 元信息\n\n...(Markdown 正文，不含 frontmatter)",
  "meta": {
    "source": "https://mp.weixin.qq.com/...",
    "doc_type": "技术博客",
    "journal": "药学学报",
    "date": "2026-09-02",
    "created": "2026-09-02 17:00",
    "tags": ["单细胞", "参考映射", "白话"],
    "summary": "解读 Cell 观点文：用参考映射做快速自动化单细胞分析"
  }
}
```

服务端会：① 按 `kind` 选目录；② 校验 `slug` 前缀与合法字符；③ 组装 YAML frontmatter（resource 强制 `category: uncat`、禁 `parent_paper`）；④ 写文件；⑤ **自动 `rebuild()`（含 lint_kb + gate_v2 硬闸）**。返回 `{"slug": "...", "entries": [...], "categories": [...]}`；若硬闸失败会在响应中回显错误。

> 调法示例（agent 侧用任意 HTTP 客户端，或本机用 curl）：
> ```bash
> curl -X POST http://localhost:8766/api/entry/create \
>   -H 'Content-Type: application/json' \
>   -d '{"kind":"resource","slug":"resources_demo","title":"demo","body":"## #0 元信息\n\n正文","meta":{"doc_type":"技术博客","tags":["x"]}}'
> ```

#### 4.3.3 HTTP 接口 `/api/ingest`（**当前推荐**：原样投递已成型的 Markdown）

4.3.2 的 `/api/entry/create` 是「结构化入参 → 服务端重组 frontmatter」，对 `pipeline_version` / `note_type` / `parent_paper` 这类流水线字段是**有损**的。`/api/ingest` 改为直接接收**已含 frontmatter 的完整 Markdown**，服务端原样落盘，不重组任何字段——契约零损耗。

请求体：

```json
{
  "files": [
    {"path": "content/papers/x_论文.md",           "content": "---\ntitle: ...\npipeline_version: paper-pipeline-v2\n---"},
    {"path": "content/notes/x_论文拆解.md",         "content": "---\nkind: note\nnote_type: paper_analysis\n...\n---\n## #0. 原始论文识别..."},
    {"path": "content/notes/x_论文白话解读.md",      "content": "---\nnote_type: paper_explainer\n...\n---"}
  ],
  "build": true
}
```

服务端行为与安全边界：

- 路径白名单：仅 `content/{papers,notes,resources}/*.md`，禁止 `..` 目录穿越与非 `.md`。
- 写盘用 `temp` + `os.replace` **原子替换**，不会留下半个文件。
- `build=true` 时以**子进程**跑 `build.py`（双闸），避免 build 内 `sys.exit` 崩掉服务线程。
- 返回：`{"written":[...], "build":{"ok":true,"exit":0,"log_tail":"..."}}`。`build.ok=false` 时读 `log_tail` 定位违规，**修正后重投同一接口**即可（已写文件保留，便于迭代修正）。
- CORS 已开（`*`），浏览器与脚本均可跨域调用。

agent 侧不必手拼 JSON，用仓库自带的助手脚本：

```bash
# 先把生成的 markdown 写到任意临时目录，再按 "本地文件@目标content路径" 投递
python ingest.py \
  "C:/tmp/x_papers.md@content/papers/x_论文.md" \
  "C:/tmp/x_deep.md@content/notes/x_论文拆解.md" \
  "C:/tmp/x_explain.md@content/notes/x_论文白话解读.md"

# 只想触发重建（无新文件）
curl -X POST http://127.0.0.1:8766/api/build
```

> ⚠️ `server.py` 的写入/管理 API **不带鉴权**（与现有分类管理 API 同一信任模型，仅用于本机/内网）。若暴露到公网，务必在前面加反向代理做鉴权，且**绝不要把 LLM apikey 放进 server.py**。

### 4.4 为什么 apikey 不该放在服务端

反向代理范式的核心安全收益：**apikey 只活在 agent 会话，常驻存储端（文件 / `server.py`）零密钥**。

- 旧范式：后台服务持有 apikey → 一旦服务被攻破，密钥泄露；且密钥长期驻留磁盘/配置。
- 反向代理：agent 会话结束，密钥随之消失；存储端只是「无状态写入接口」，攻破它也拿不到任何 LLM 凭证。

`paper_pipeline/` 包里的确定性逻辑（去重、Canonical 校验、语义 Gate、staging）**完全不需要 apikey**——它们只处理 agent 已经产出的结构化结果。这正是「智能在 agent、确定性在代码」的干净边界。

### 4.5 `paper_pipeline/` 的角色（互补而非替代）

`paper_pipeline/` 不是「旧范式」的代名词，而是反向代理范式中**agent 完成理解后、由代码兜底的确定性层**：

- `identity.py` / `source_manifest.py`：身份解析 + 去重拦截（防止同一篇论文重复入库）。
- `model.py` / `frontmatter_schema.py`：Canonical 结构与 frontmatter 校验（与 `lint_kb.py` 对齐）。
- `semantic_gate.py`：语义级 Gate（覆盖度 / 数值一致性 / 未支撑论断 / 对齐 / 深度）。
- `staging.py` / `run_manifest.py`：阶段性写入 + 原子提交/回滚 + `resume`（断点续跑）。

agent 负责「读得懂、拆得开、写得对」；`paper_pipeline/` 负责「校验得了、恢复得回、复现得出」。二者通过「agent 产出 Markdown / Canonical → 代码校验持久化」的契约协作，而不是由代码去抢 LLM 的活。

---

## 5. 端到端示例（一条链接如何变成两篇笔记 + 一个论文条目）

以「用户发来一篇 arXiv 论文链接，要求 v2 新版解析」为例：

1. **读源**：agent `WebFetch` / 原生连接器取论文文本（标题、作者、摘要、方法、结果数值）。
2. **判路线**：`article-summarizer` 步骤 0 → 命中 PAPER（arxiv 域名 + 原文）。
3. **定位**：若输入是解读帖则 `paper-locator` 反查原始论文；本例已是原文，跳过。
4. **拆解**：`paper-reader` 产出 `#0–#9` 双栏（【专业描述】+【通俗解释】）。
5. **白话**：按 7 节模板产出「论文白话解读」（【专业描述】+【白话解释】+ 术语表）。
6. **落库（写入接口二选一）**：
   - 文件接口：直接写 `content/papers/{slug}_论文.md` + 两篇 `content/notes/{slug}_*.md`；
   - 或 HTTP 接口：连续 `POST /api/entry/create` 三次（paper / 拆解 note / 白话 note），`meta` 里带上 `pipeline_version: paper-pipeline-v2`、`note_type`、`parent_paper`。
7. **校验**：`python build.py` → `lint_kb.py` 过 kind/隔离/双栏 → `gate_v2.py` 过 v2 挂载完整性 + 指标一致性。任一不过，agent 回到第 4–6 步修正（这就是「agent 在环自检」）。
8. **呈现**：`present_files` 把 `.md` 推给用户；本地 `server.py` 已可浏览。

---

## 6. 校验与安全小结

| 保证层 | 机制 | 防什么 |
|---|---|---|
| 路由层 | `article-summarizer` 步骤 0 先判 PAPER/RESOURCE | 误用另一套模板/落点 |
| 写入层 | `content/` 三目录 + frontmatter 契约 | 目录/契约不混 |
| 硬闸层 | `build.py` → `lint_kb.py` + `gate_v2.py` | 资源进文献库 / 模板串流 / v2 缺笔记 / 指标冲突 |
| 视图层 | `library` 只取 `papers()`，`knowledge` 只取 `resources()` | 即便写错 kind 也被前端兜底 |
| 密钥层 | apikey 仅存 agent 会话，存储端零密钥 | 常驻服务密钥泄露 |

---

## 7. 常见坑

- **frontmatter 的 `---` 被粘连**：给论文加字段时若正则把 closing `---` 与前一字段拼成 `item_type: journalArticle---`，frontmatter 失效、`lint_kb.py` 报 `kind=''`。修复：拆开 `---` 独占一行。
- **资源误写 `parent_paper` / 具体 `category`**：会触发 `lint_kb.py` 隔离违规 → build 失败。记住资源 `kind:resource`、`category:uncat`、无 `parent_paper`。
- **白话解读写了可量化指标**：可能与拆解数值冲突触发 `gate_v2` `CONSISTENCY_GATE`；建议白话侧只定性、指标集中在拆解侧。
- **写入接口在公网未鉴权**：`server.py` 管理/写入 API 无鉴权，公网部署务必加反代鉴权，且**不要**把任何 LLM apikey 放进服务端。
- **本仓库只含框架代码**：`content/papers/*`、`content/notes/*`、`categories.json`、`dist/`、`_papers_archive/`、`_runs/` 均被 `.gitignore` 排除；`content/resources/` 也按本地数据对待（见仓库 `.gitignore`）。clone 下来是空架子，填你自己的文献即可。
