# Weekly Trend

每周自动抓取 [GitHub Trending（本周）](https://github.com/trending?since=weekly)，
借助 LLM 整理成一份分类、带图的**中文周刊**，并自动写回仓库。

往期周刊见 [`reports/`](./reports)。

## ✨ 特性

- 🔍 抓取本周 Trending 仓库（名称、描述、语言、star、本周 star 等）
- 📖 自动补全每个仓库的 README、主页链接、topics
- 🖼️ 无头浏览器截图 + 多模态识别，**只保留项目相关图片**（过滤徽章/头像）
- 🗂️ LLM 按主题**分类**生成中文周刊正文
- 🤖 GitHub Actions 每周定时运行，自动 commit 归档「第 N 期」

## 🔄 工作流程

```
crawler → enrich → filter_images → generate_report → output_report
 抓列表    补全README    截图+识图       生成分类正文        写入 reports/
```

基于 [LangGraph](https://github.com/langchain-ai/langgraph) 编排，节点代码见 `src/graph/nodes/`。

## 🚀 快速开始

```bash
# 1. 安装依赖（使用 uv）
uv sync
uv run playwright install chromium   # 截图所需的浏览器

# 2. 配置环境变量
cp .env.example .env                  # 然后填入 OPENAI_API_KEY

# 3. 运行
uv run python src/main.py
```

生成的周刊在 `reports/YYYY_MM_DD.md`，配图在 `reports/assets/<期数>/`。

> 未配置 `OPENAI_API_KEY` 时会直接跳过、不执行后续步骤。

## ⚙️ 环境变量

| 变量 | 必填 | 默认 | 说明 |
|------|:---:|------|------|
| `OPENAI_API_KEY` | ✅ | — | OpenAI 密钥 |
| `OPENAI_MODEL` | | `gpt-4o` | 模型名（需支持视觉） |
| `OPENAI_BASE_URL` | | 官方 | 走代理 / 自建网关时填 |
| `README_MAX_CHARS` | | `32000` | README 截断长度（字符） |
| `WEEKLY_CONCURRENCY` | | `8` | 并行处理仓库的并发数 |
| `GITHUB_TOKEN` | | — | 提高 GitHub API 速率限制（CI 自动注入） |

## 🤖 CI

`.github/workflows/weekly.yml` 每周一 00:00 UTC 自动运行（也支持手动触发）。
使用前在仓库 **Settings → Secrets** 配置 `OPENAI_API_KEY`，生成后会自动 commit 回仓库。

## 📄 文档

- 产品需求文档：[`docs/PRD.md`](./docs/PRD.md)

## License

[MIT](./LICENSE) © 2026 yliu
