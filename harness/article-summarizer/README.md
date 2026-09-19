# 文章总结器（Article Summarizer）Harness

统一的「文章总结」流水线，把**论文导入**与**知识资料导入**合并为一个 Harness。
任何输入进来，**第一步永远是判定路线**，判定后才走对应分支；两条分支物理隔离、互不串流。

## 目录
```
article-summarizer/
├── manifest.yaml            # Harness 注册清单（被 Hub Registry 自动扫描）
├── specs/harness.yaml       # 工作流规格
├── skills/
│   ├── article-summarizer.md  # 统一入口技能（路由 PAPER/RESOURCE）
│   ├── paper-locator.md       # 定位原始论文
│   └── paper-reader.md        # 论文深度拆解（#0–#9 双栏）
└── prompts/
    └── summary-format.md      # 非论文知识资料总结格式
```

## 路线
- **PAPER**：论文 / 可定位原文的公众号·B站解读 → 定位 → 拆解 → 作为 `paper`+`note` 导入文献库
- **RESOURCE**：非论文材料 / 定位不到原文的解读 / 综述·论坛·文档·工具介绍·访谈·新闻 / 批判观点争议 →
  按 `summary-format.md` 总结 → 作为 `kind:resource` 独立导入「知识资料」（只在知识库显示）

## 注册与查看
- 本目录被 `harness-management` 的 Registry 自动扫描（每次请求 `refreshRegistry`）。
- Hub API：`GET /api/harnesses/article-summarizer`、`GET /api/harnesses/article-summarizer/files`
- Hub 控制台：http://127.0.0.1:4173/
- 知识库站点（kb-site）的「Skill 管理」面板改为从 Hub 拉取本 Harness 的元信息与 skill/prompt 内容查看。

## 执行
由 WorkBuddy Agent 加载 `skills/` 下的技能与 `prompts/` 下的总结格式编排执行；
Hub 仅作统一注册、目录与 Skill/Prompt 管理，不直接 spawn 进程（`runtime.type: http`）。
