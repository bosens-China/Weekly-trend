# Weekly Trend · 产品需求文档（PRD）

## 1. 背景与目标

GitHub Trending 每天都在变，但开发者很难持续跟进。本项目通过 CI 定时抓取
**GitHub Trending（本周）**，借助 LLM 自动整理成一份**中文周刊**并写回仓库，
形成可订阅、可归档的「第 N 期」内容。

目标：**全自动、零人工**地产出结构清晰、带图、分类的每周技术趋势周刊。

## 2. 使用场景

- 开发者 / 技术团队订阅仓库，每周一自动收到新一期周刊。
- 作为公众号 / 博客 / Newsletter 的素材来源。

## 3. 功能需求

| 编号 | 功能 | 说明 |
|------|------|------|
| F1 | 抓取 Trending | 抓 `https://github.com/trending?since=weekly`，解析仓库名、描述、语言、star、本周 star、贡献者等 |
| F2 | 仓库信息补全 | 调 GitHub API 获取 README、主页链接（homepage）、topics |
| F3 | 图片下载 + 识别 | **仅当 README 含图片时**逐张下载候选图为本地文件（按 Content-Type 定格式），再用多模态模型结合 README 上下文挑出「项目相关图」（截图/Logo/架构图），过滤徽章、头像等 |
| F4 | 报告生成 | LLM 将所有仓库**按主题分类**，生成中文 Markdown 正文，嵌入选中的本地图片 |
| F5 | 输出归档 | 每期一个日期文件夹 `reports/YYYY_MM_DD/`，内含 `README.md` 与 `assets/`；带「第 N 期 + 日期」头部；**期数 = 已有日期文件夹数 + 1**。图片先下载到临时目录，**仅被正文引用到的**才移入 `assets/` |
| F6 | CI 自动化 | GitHub Actions 每周一定时触发，生成后自动 commit 回仓库 |

## 4. 非功能需求

- **成本可控**：README 截断（`README_MAX_CHARS`，默认 32k）、单仓库候选图上限 8 张；**缓存** enrich 结果与视觉判定（`cache/` 提交进仓库供 CI 跨周复用；`CACHE_TTL_DAYS` 默认 30 天，超期自动清理），重跑/跨周复现的仓库不重复抓取与调模型。
- **健壮兜底**：
  - 未配置 `OPENAI_API_KEY` → 直接跳过，不执行后续。
  - README 无图 / 抓取失败 → 跳过该仓库的图片处理，不影响整体。
  - GitHub API 限流 / 单图下载失败 / 非图片响应 → 记录日志并继续。
- **并发**：仓库信息补全与图片下载并行，线程数由 `WEEKLY_CONCURRENCY` 控制（默认 8）。

## 5. 技术方案

- **编排**：[LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph`，
  五个节点串联：`crawler → enrich → filter_images → generate_report → output_report`。
- **LLM**：OpenAI 兼容的视觉模型（默认 `gpt-4o`，也可接 MiMo 等），经 `langchain-openai`。
- **抓取**：`httpx` + `selectolax`（Trending 页）、GitHub REST API（README/主页）、`httpx` 下载 README 图片。
- **图片相关性**：多模态模型，图片以 base64（data URL）传入，结合 README 文字上下文判定。
- **自动化**：GitHub Actions（cron + 手动触发）。

### 状态流转（WeeklyState）

```
repos          # crawler 产出的原始仓库列表
  ↓ enrich
enriched       # 补全 README / homepage / topics / 图片候选
  ↓ filter_images
enriched.relevant_images   # 下载到临时目录 + 多模态筛选后的图片（相对路径 assets/xxx）
issue_number / date_str / tmp_assets_dir   # 期数、日期、候选图临时目录
  ↓ generate_report
report_md      # 分类后的中文周刊正文
  ↓ output_report
output_path    # reports/YYYY_MM_DD/README.md（被引用的图移入同目录 assets/）
```

## 6. 输出规范

- 目录：每期一个 `reports/YYYY_MM_DD/`，内含 `README.md` 与 `assets/*.png`（仅保留被正文引用的图）。
- 头部：`# GitHub 一周热点 · 第 N 期` + 日期 + 数据来源。
- 正文：按主题分类，每个项目含标题、star/语言信息、中文简介、可选配图、官网链接。

## 7. 后续可扩展

- README 无图时用项目主页截图兜底当封面。
- 支持 daily / monthly 周期。
- 增加 RSS / 邮件推送。
