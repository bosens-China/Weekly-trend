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
| F3 | 图片截图 + 识别 | **仅当 README 含图片时**启动无头浏览器逐张截图存为本地 PNG，再用多模态模型挑出「项目相关图」（截图/Logo/架构图），过滤徽章、头像等 |
| F4 | 报告生成 | LLM 将所有仓库**按主题分类**，生成中文 Markdown 正文，嵌入选中的本地图片 |
| F5 | 输出归档 | 写入 `reports/YYYY_MM_DD.md`，带「第 N 期 + 日期」头部；**期数 = 已有周刊数 + 1** |
| F6 | CI 自动化 | GitHub Actions 每周一定时触发，生成后自动 commit 回仓库 |

## 4. 非功能需求

- **成本可控**：README 截断（`README_MAX_CHARS`，默认 32k）、单仓库截图上限 8 张。
- **健壮兜底**：
  - 未配置 `OPENAI_API_KEY` → 直接跳过，不执行后续。
  - README 无图 / 抓取失败 → 跳过该仓库的图片处理，不影响整体。
  - GitHub API 限流 / 单图截图失败 → 记录日志并继续。
- **并发**：仓库信息补全与图片截图并行，线程/协程数由 `WEEKLY_CONCURRENCY` 控制（默认 8）。

## 5. 技术方案

- **编排**：[LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph`，
  五个节点串联：`crawler → enrich → filter_images → generate_report → output_report`。
- **LLM**：OpenAI（默认 `gpt-4o`，自带视觉），经 `langchain-openai`。
- **抓取**：`httpx` + `selectolax`（Trending 页）、GitHub REST API（README/主页）。
- **截图**：`playwright`（Chromium，异步并发）。
- **自动化**：GitHub Actions（cron + 手动触发）。

### 状态流转（WeeklyState）

```
repos          # crawler 产出的原始仓库列表
  ↓ enrich
enriched       # 补全 README / homepage / topics / 图片候选
  ↓ filter_images
enriched.relevant_images   # 截图 + 多模态筛选后的本地图片路径
issue_number / date_str    # 期数与日期
  ↓ generate_report
report_md      # 分类后的中文周刊正文
  ↓ output_report
output_path    # reports/YYYY_MM_DD.md
```

## 6. 输出规范

- 文件：`reports/YYYY_MM_DD.md`，图片资产：`reports/assets/<期数>/*.png`。
- 头部：`# GitHub Trending 周刊 · 第 N 期` + 日期 + 数据来源。
- 正文：按主题分类，每个项目含标题、star/语言信息、中文简介、可选配图、官网链接。

## 7. 后续可扩展

- README 无图时用项目主页截图兜底当封面。
- 支持 daily / monthly 周期。
- 增加 RSS / 邮件推送。
