---
name: article-summarizer
description: "统一「文章总结器」：收到任意文章链接/文本后，先判定路线再总结。PAPER 路线：原始论文（含公众号/B站/视频中明确讲解且能定位原文的具体论文）→ paper-locator 定位 → paper-reader 拆解 → 作为 paper+note 导入文献库。RESOURCE 路线：非论文材料（定位不到原文的公众号解读、综述/论坛帖/官方文档/工具或产品介绍/访谈/新闻、以及批判/观点/争议类文章）→ 按 summary-format.md 总结并作为 kind:resource 独立导入「知识资料」（只在知识库显示）。两路线严格隔离，物理上互不串流。"
agent_created: true
---

# 文章总结器（Article Summarizer · 统一入口）

把「论文导入」与「知识资料导入」合并为**一个 harness**。任何输入进来，**第一步永远是判定路线**，
判定后才走对应分支；两条分支的写入契约互不重叠，并由 `scripts/lint_kb.py`（build 硬闸）兜底，
保证资源绝不进文献库、论文模板绝不污染知识资料。

## 平台路径

- 站点源码：`E:\Agent WorkSpace\WorkBuddy\kb-site\`
- 论文：`content/papers/` + 挂载笔记 `content/notes/`
- 知识资料：`content/resources/`（独立条目，无 parent_paper）
- 构建：`C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe E:\Agent WorkSpace\WorkBuddy\kb-site\build.py`
- 非论文总结格式：`E:\Agent WorkSpace\WorkBuddy\kb-site\.workbuddy\skills\article-summarizer\summary-format.md`
- 论文拆解模板（用户级技能）：`paper-reader`（输出 `#0–#9` 双栏，与资源路线**绝不混用**）
- 内容契约检查：`E:\Agent WorkSpace\WorkBuddy\kb-site\scripts\lint_kb.py`

## 步骤 0：判定路线（必须最先做，先分类再总结）

拿到链接/文本后，先输出一句判定并说明理由，再动手：

**→ PAPER（走论文路线）** 当输入是**原始研究产物**之一：
- 链接域为 `arxiv.org` / `doi.org` / `biorxiv.org` / `medrxiv.org` / `openreview.net` / 期刊会议官网（nature/cell/science/ieee/acm/pmc 等） / 论文 PDF 直链；
- 或正文是论文**自己的** Methods/Results/Experiments/benchmarks（而非别人转述）。
- **（关键修正）公众号 / B站 / 视频等二手材料，只要它明确是「对某篇具体论文的解读 / 详解 / 一文读懂 / 速览」且能定位到原始论文**（arxiv / doi / 期刊官网 / 论文 PDF；判定信号：帖子点名具体论文标题+作者+期刊/年份、给出 DOI 或 arXiv 编号、或能从内容可靠反查出原始论文）→ **视为该论文的入口，走 PAPER 路线**：先用 paper-locator 定位原始论文，再以原文为主用 paper-reader 做深度拆解，作为 paper+note 导入文献库。

**→ RESOURCE（走非论文路线）** 当输入是**二手/非研究产物且不属于「可定位论文的解读」**：
- 对一篇论文的「解读 / 详解」类文章，但**定位不到原始论文**（无标题/作者/期刊/DOI/arXiv，或反查不到）→ RESOURCE，`doc_type` 选 `技术博客`；
- 综述 / 论坛帖 / 官方文档 / 教程；
- 工具介绍 / 产品介绍 / 新闻 / 访谈；
- **批判 / 观点 / 争议类文章**（如某模型的 hype 拆解、某公司技术报告评议）——即便围绕某篇论文，本质不是「论文本身的研究产物」，走 RESOURCE；这类常和公司博客/争议事件绑定，可信度层级异于期刊论文，须在 #0 显式标注；
- 对多篇论文的泛泛「月度综述 / 领域盘点」。
- **（裁决规则·2026-09-14 新增，同日精修：底层文章类型优先于「能否定位」，但期刊栏目名不是决定性标签）** 即使公众号帖点名了论文标题 + DOI / arXiv 号、可精确定位，若**底层文章本身不是研究产物**——观点 / 展望 / 评论 / Editorial / 路线图 / 问题清单（无实验、无方法、无结果数据、无文献证据链综合）——走 **RESOURCE**（`doc_type: 综述`）。理由：paper-reader 的 #0–#9 是实验型模板，对纯主张文章只会产出空节堆砌。**判据一句话：底层文章有无可拆解的实质内容（实验 / 方法 / 结果 / 系统性文献综合）？有 → PAPER；只有主张与清单 → RESOURCE。**
  - **期刊栏目名（如刊面印的 "Perspective"）不是决定性判据**，要看内容形态：
    - **清单式 / 主张式 Perspective**（零实验、零综合，只有一堆论点）→ RESOURCE。判例：Cell《Fifteen challenges for generative AI applications to cell biology》（DOI 10.1016/j.cell.2026.07.004，完全可定位）→ RESOURCE / 综述。
    - **系统性 Review & Synthesis**（20 年文献证据链、机制综合、元分析引用、病理图谱等厚内容）→ **PAPER**，与库内综述先例一致（NRG《Interpretation, extrapolation and perturbation of single cells》、Nature Medicine《How to build an AI-driven digital organism》、Trends《Multicellular ecosystems》等 5 篇综述均在 papers）。判例：Neuron Menon《20 years of the default mode network》（DOI 10.1016/j.neuron.2023.04.023，刊面印 "Perspective" 但为系统性综述）→ PAPER。综述走 PAPER 时 #2–#5 可映射为「概念界定 / 历史脉络 / 机制综合 / 证据域汇总」，无需强填实验数据。
  - 对照判例（→ PAPER，研究型论文）：公众号解读 Cancer Cell 研究论文 UniCure（有模型 / 数据 / 实验结果）→ PAPER。
  - **分类注意**：综述走 PAPER 时 category 按内容域选——AI+Bio 综述用 `collection_241`；非 AI+Bio 领域（如神经科学）用 `uncat`（先例 male_fly_connectome_weixin），不要硬塞进不相关的分类树分支。

**→ AMBIGUOUS（默认 fail-safe 落 RESOURCE）**：
- 拿不准到底是「可定位论文的解读」还是「泛化观点/新闻」时，**宁可 RESOURCE，绝不污染文献库**；但一旦能可靠定位原始论文，就应走 PAPER。

> ⚠️ 关键边界：同一篇论文可能存在「论文 PDF」（PAPER）和「公众号解读帖」（RESOURCE）两种输入。
> - 若公众号帖**明确讲解某篇可定位的论文**、且该论文**本身是研究产物（有方法/实验/结果）** → 走 **PAPER**（定位原文、以原文拆解为主），这是本技能的默认正路；
> - 若公众号帖**定位不到原文**、或底层文章**本身是观点/综述/Perspective（无可拆解实验）**、或本质是对论文的**批判 / 观点 / 新闻** → 走 **RESOURCE**。
> 二者产物互不可混：PAPER 产 papers+notes（进文献库），RESOURCE 产独立 resources（只在知识库）。

---

## 步骤 0.5：查重（分支 A 必做，先查再写）

不管感觉多"肯定是新论文"，**生成 markdown 之前必须查重**，否则会重复入库或与并发流程打架：

```bash
cd "E:\Agent WorkSpace\WorkBuddy\kb-site"
ls content/papers content/notes | grep -i -E "<标题核心英文词>"
grep -rl "<DOI 或 arXiv 编号>" content/papers content/notes 2>/dev/null
```

- 命中**同一篇**（DOI / arXiv 编号 / `canonical_paper_id` 一致）→ **停止生成**，向用户报告"已存在，跳过"并给出已有条目路径；只有用户明确要求时才重写升级。
- **版本变体也算同一篇**：同一工作的预印本（bioRxiv/arXiv）与期刊正式版 DOI 不同。因此除 DOI 外，必须再按**核心标题词 + 一作/通讯作者姓氏**做一轮宽 grep（`grep -rl -i "<标题词>\\|<作者姓>" content/`）——2026-09-14 的 STATE 案例：链接讲预印本（bioRxiv 2025.06.26.661135），库内已有期刊版条目（Cell，DOI 10.1016/j.cell.2026.07.052），仅查 DOI 会漏。命中变体 → 跳过；若用户要求"升级为期刊版"，**原地更新**既有条目的 DOI/期刊/卷期字段，不新开条目。
- 命中文件但内容偏薄或有事实错误（术语用错、缺 DOI/作者单位）→ 可**覆盖升级**，并在汇报里说明改了什么。
- 未命中 → 正常往下走。

> 教训（2026-09-13）：同一批链接可能已被并发流程处理过，或历史上导入过。不查重会静默产出重复条目；查一次成本几乎为零。

---

## 分支 A：PAPER 路线（论文）

> 下面各「写 X.md」步骤均指**先生成到临时目录**（如 `C:/tmp/`），最终统一经文末「步骤 5：落库接口」写入，**不要直接用 Write 工具写 `kb-site/content/`**。

1. 调用用户级技能 **`paper-reader`** 产出 `#0–#9` 双栏拆解 MD（从 `## #0.` 开始，含【专业描述】/【通俗解释】）。
   - 若输入是公众号/视频，paper-reader 会先定位原始论文、以原文为主，这是预期行为。
2. 写论文条目 `content/papers/{英文简称}_论文.md`：
   ```yaml
   ---
   title: <论文英文原名>
   type: paper
   category: <从 ALLOWED_CATEGORIES 选，不确定选 uncat>
   journal: <期刊/会议>
   date: <YYYY-MM-DD>
   created: <YYYY-MM-DD HH:MM 必填>
   source: <原文链接>
   doi: <DOI>
   tags: [tag1, tag2, tag3]
   summary: <一句话核心贡献，≤220字（这是「摘要」，长文，与 一句话概括 分开写）>
   一句话概括: <≤140字一句话电梯演讲：是什么/解决什么问题/为什么值得记，只陈述事实>
   pipeline_version: paper-pipeline-v2
   ---
   ```
   （`ALLOWED_CATEGORIES` 见下；禁止新建分类。）
   - **frontmatter 必须含 `一句话概括:` 字段（一句话电梯演讲，≤140 字：是什么 / 解决什么问题 / 为什么值得记；只陈述事实，不展开评价）**——这是与旧数据（如 PULSE）统一的硬约束字段，所有 `kind:paper` 条目都必须有，`lint_kb` 会校验，缺失即构建失败；该字段由前端主表格/卡片紧随标题展示，与 `summary`（摘要，长文）互不影响、必须分开写。
3. 写挂载笔记 `content/notes/{英文简称}_论文拆解.md`：
   ```yaml
   ---
   kind: note
   parent_paper: papers_{论文slug}   # = papers_ + 论文文件名去 .md（含 _论文）。例：epibench_论文.md → papers_epibench_论文
   title: <中文译名>
   type: note
   note_type: paper_analysis
   category: uncat
   pipeline_version: paper-pipeline-v2
   tags: []
   ---
   ```
   正文 = paper-reader 完整输出（从 `## #0.` 开始，双栏【专业描述】+【通俗解释】）。
   > ⚠️ **防呆（2026-09-14 实测）**：拆解笔记的 frontmatter **只能是上面那份 note 模板**——不要把论文条目的 frontmatter（`type: paper`/summary 等）一并复制到文件顶部，lint 会读到 `type: paper` 判 kind 契约违规（PromViL 案例踩坑：论文 FM + 笔记 FM 叠放，报 `notes/ 下 kind 应为 note，实际='paper'`）。

4. 写白话解读笔记 `content/notes/{英文简称}_论文白话解读.md`（**v2 论文必产，gate_v2 强制校验；漏写会导致 build 通过但 gate_v2 失败**）：
   ```yaml
   ---
   kind: note
   parent_paper: papers_{论文slug}
   title: <中文译名> 白话速读
   type: note
   note_type: paper_explainer
   category: uncat
   pipeline_version: paper-pipeline-v2
   tags: [<领域>, <方法>, 白话]
   ---
   ```
   正文 = **固定 7 节双栏模板**（每节 `**【专业描述】**` + `**【白话解释】**`，顺序不可改、不可合并、缺栏即不合格）：
   - `## 一句话看懂`
   - `## 为什么要做`
   - `## 核心思路`
   - `## 大概怎么做`
   - `## 做出了什么`
   - `## 最终怎么理解`
   - `## 专业术语文白对照`（3 列表格：专业术语 / 白话理解 / 在本文中的作用）
   事实须与 ③ 拆解对齐，关键指标数值不得冲突（gate_v2 会跨笔记核对 Pearson/Spearman/p/F1/准确率/AUC 等）。
   > ⚠️ **一致性闸的精确规则（2026-09-14 实测）**：gate_v2 用正则从两份笔记正文抽取同名指标，**当两侧集合都非空时必须完全相等**（一侧为空则放行）。抽取用的是 `AUC\s*[=:]?\s*(\d+\.\d+)` 这类「指标词紧跟数值」的模式——因此**只要拆解里出现 `AUC 0.xxxx`，白话里也必须出现同一个数值集合**，反之亦然。踩坑实例：拆解写了 `AUC 0.8616` 与 `AUC 0.7155`、白话只写了 `AUC 0.8616` → `FAIL CONSISTENCY_GATE: AUC 拆解={'0.7155','0.8616'} 白话={'0.8616'}`，build 直接失败。
   > **修复姿势（推荐）**：让两份笔记在「做出了什么 / #7 关键结果」里**用同样的指标表述完整列出同一组数值**（如 `AUC 0.8616`、`AUC 0.8123`、`AUC 0.7155`、`AUC 0.6203`）；不要在两侧写不同的子集。
   > **投递前自检（30 秒，强烈建议）**：直接调用闸门自己的抽取器比对，命中即修，避免一轮无效 ingest——
   > ```bash
   > cd "E:/Agent WorkSpace/WorkBuddy/kb-site" && <python> -c "
   > import sys,re; sys.path.insert(0,'.')
   > from gate_v2 import extract_indicators
   > body=lambda p:re.sub(r'^---\s*\n.*?\n---\s*\n','',open(p,encoding='utf-8').read(),1,re.DOTALL)
   > d=extract_indicators(body('<拆解md>')); p=extract_indicators(body('<白话md>'))
   > print(d,p,[(k,d.get(k,set()),p.get(k,set())) for k in set(d)|set(p) if d.get(k,set()) and p.get(k,set()) and d.get(k,set())!=p.get(k,set())] or 'OK')"
   > ```

5. 见下方「步骤 5：重建 + 硬闸校验」。

**ALLOWED_CATEGORIES**（只可选，禁新建）：
`collection_24`生信 · `collection_230`其他[`collection_231`纯实验,`collection_26`课题组文献,`collection_229`因果模型Project参考文献] · `collection_232`AI[`collection_236`大模型优化,`collection_235`理论,`collection_234`AI4S] · `collection_233`AI+Bio[`collection_239`基础模型,`collection_237`设计,`collection_240`预测,`collection_241`综述,`collection_25`LLM+Bio[`collection_238`语料库,`collection_72`智能体]] · `uncat`待归类。

---

## 分支 B：RESOURCE 路线（非论文知识资料）

> 下面「写 X.md」步骤指**先生成到临时目录**，最终统一经「步骤 5：落库接口」写入，**不要直接写 `kb-site/content/`**。

1. 判定 `doc_type` ∈ `技术博客 / 综述 / 论坛帖 / 官方文档 / 文本 / 新闻`。
2. 严格按 `summary-format.md` 总结（核心观点 / 技术要点 / 关键数据 / 方法流程 / 定位 / 局限 / 可迁移 / 术语表）。
   **禁止套论文拆解模板**（不写「论文信息 / 论文 Story / 作者想回答的问题」那套）。
   区分「论文原文说」与「博主/作者解读」，不把解读当结论；数字必标口径。
   **frontmatter 必须含 `一句话概括:` 字段（一句话电梯演讲，≤140 字：是什么 / 解决什么问题 / 为什么值得记；只陈述事实，不展开评价）**——这是 summary-format 的硬约束字段，所有 `kind:resource` 条目都必须有，`lint_kb` 会校验，缺失即构建失败；该字段由前端主表格/卡片紧随标题展示，与 `summary`（摘要，长文）互不影响、必须分开写，也独立于下面的「一段话看懂」段落。
3. 写 `content/resources/{短英文或拼音 id}.md`（slug 自动变 `resources_{id}`，无需手写前缀）：
   ```yaml
   ---
   title: <忠实标题>
   kind: resource
   doc_type: <技术博客 / 综述 / 论坛帖 / 官方文档 / 文本 / 新闻>
   category: uncat          # 固定 uncat：资源不参与文献库分类树，写具体分类反会被筛选隐藏
   source: <原文链接>
   journal: <出处名，如公众号名/站点名>   # 显示在知识卡片副标题
   authors: [<作者或机构>]
   date: <YYYY-MM-DD 发布日期>
   created: <YYYY-MM-DD HH:MM 录入时间，必填>
   tags: [tag1, tag2, tag3]   # 3-5 个，含领域 + 方法
   summary: <一句话核心，≤140字，这是「摘要」长文，与 一句话概括 分开写>
   一句话概括: <≤140字一句话电梯演讲：是什么/解决什么问题/为什么值得记，只陈述事实>
   ---
   ```
   正文从 `## #0 元信息` 开始（见 summary-format.md）。不要写重复 `# 标题`、不要写 `[TOC]`。
4. **隔离铁律**（被 lint 硬闸强制）：`kind` 必须精确 `resource`；**绝不写 `parent_paper`**（资源是独立笔记）；`category` 固定 `uncat`。
5. 见下方「步骤 5：重建 + 硬闸校验」。

---

## 步骤 5：落库 + 重建 + 硬闸校验（接口化，两分支共用，必做）

**不要直接用 Write 工具写 `kb-site/content/*.md`，也不要本地跑 `build.py`**——落库与构建统一走 kb-site 的 HTTP 接口，由服务端原子写盘并触发双闸（这是「接口化」的核心：Agent 只产出 markdown 文本并 POST，kb-site 的 `content/` 目录只由服务端持有）。

1. 把上面各步生成的 markdown 先写到**临时目录**（如 `C:/tmp/`），文件名任意，但记住各自目标路径：
   - 论文条目 → `content/papers/{英文简称}_论文.md`
   - 拆解笔记 → `content/notes/{英文简称}_论文拆解.md`
   - 白话解读 → `content/notes/{英文简称}_论文白话解读.md`
   - 资源     → `content/resources/{id}.md`
2. 调用落库接口（二选一）：
   - **推荐**：用 kb-site 自带助手脚本（cwd 设为 kb-site 根目录）
     ```bash
     C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe ingest.py \
       "C:/tmp/xxx_papers.md@content/papers/xxx_论文.md" \
       "C:/tmp/xxx_deep.md@content/notes/xxx_论文拆解.md" \
       "C:/tmp/xxx_explain.md@content/notes/xxx_论文白话解读.md"
     ```
     （`本地文件@目标content路径` 形式；若本地文件本身就在 content/ 下可省略 `@target`。脚本 POST 到 `POST /api/ingest`，服务端原子写盘后立即跑 `build.py` 双闸。）
   - 或裸调接口：`POST http://127.0.0.1:8766/api/ingest`，body `{"files":[{"path":"content/papers/xxx_论文.md","content":"<完整 markdown 含 frontmatter>"},...],"build":true}`。
3. 解析返回 JSON：
   - `written` 列出已落盘的文件路径；`build.ok=true` 且 `build.exit=0` 表示双闸通过。
   - 若 `build.ok=false`：读 `build.log_tail` 定位 lint/gate 违规（常见：缺 `一句话概括`、缺双栏标记、v2 论文缺白话解读笔记、拆解↔白话指标数值冲突），回到对应文件修正后**重投同一个 /api/ingest**（已写文件不会丢，便于修正），直到 `build.ok=true`。
4. 仅想重新构建（无新文件）时：`POST http://127.0.0.1:8766/api/build`。

> 接口说明（server.py）：`/api/ingest` 仅允许 `content/{papers,notes,resources}/*.md`、禁目录穿越；写盘用 temp+os.replace 原子替换；`/api/build` 等价于接口化版 `build.py`。两者均以**子进程**跑 build.py，避免 build 内 `sys.exit` 影响服务线程。CORS 已开，浏览器/脚本均可跨域调用。

- `build.py` 会自动跑**两道闸**（任一失败 → build 直接失败，dist 不 emit，从物理上阻断串流）：
  1. `scripts/lint_kb.py`：kind 契约 / resources 隔离 / 防模板串流 / notes 正文双栏格式（白话解读【专业描述】+【白话解释】、拆解【专业描述】+【通俗解释】）/ **papers / resources 必须在 frontmatter 含 `一句话概括:` 字段（标题旁的电梯演讲，缺失即失败；该字段独立于 `summary` 摘要，二者须分开写）**。
  2. `scripts/gate_v2.py`：v2 论文挂载完整性（拆解+白话解读笔记均在、parent 匹配）+ 拆解↔白话解读关键指标数值一致。
  - 两闸通过才继续构建并产出 dist。
- 额外确认隔离（以 SpineMed 样例，slug=`resources_spinemed_450k`）：
  ```bash
  C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe - <<'PY'
  import json
  d=json.load(open("dist/index.json",encoding="utf-8"))
  ents=d["entries"]
  papers=[e for e in ents if e["kind"]=="paper"]
  res=[e for e in ents if e["kind"]=="resource"]
  slug="resources_<你的文件id>"
  hit=[e for e in res if e["slug"]==slug]
  print("在知识库(resources):", "是" if hit else "否")
  print("误入文献库(papers):", "是" if any(e["slug"]==slug for e in papers) else "否")
  PY
  ```
- 用 `present_files` 推送生成的 `.md` 给用户。

## 两路线隔离保证小结

| 保证层 | 机制 | 防什么 |
|---|---|---|
| 路由层 | 步骤 0 先判定 PAPER/RESOURCE，AMBIGUOUS 默认 RESOURCE | 不误用另一套模板/落点 |
| 写入层 | 分支 A 写 papers+notes；分支 B 写 resources、禁 parent_paper、category=uncat | 目录/契约不混 |
| 硬闸层 | `build.py` 调 `lint_kb.py`，违反即失败 | resources 永不进文献库、论文模板永不污染知识资料（物理阻断） |
| 视图层 | 前端 library 只取 `papers()`，knowledge 只取 `resources()` | 即便写错 kind 也被视图层兜底挡住（单向保护） |
