# Weekly Trend

每周自动抓取 [GitHub Trending（本周）](https://github.com/trending?since=weekly)，
借助 LLM 整理成一份分类、带图的**中文周刊**，并自动写回仓库。

往期周刊见 [`reports/`](./reports)。

## ✨ 特性

- 🔍 抓取本周 Trending 仓库（名称、描述、语言、star、本周 star 等）
- 📖 自动补全每个仓库的 README、主页链接、topics
- 🖼️ 下载 README 图片 + 多模态识别，**只保留项目相关图片**（过滤徽章/头像）
- 🗂️ LLM 按主题**分类**生成中文周刊正文
- 🧮 本地缓存 enrich / 视觉判定，重跑或跨周复现的仓库**不重复抓取/调模型**
- 🤖 GitHub Actions 每周定时运行，自动 commit 归档「第 N 期」（期数台账见 `reports/index.json`）

## 🔄 工作流程

```
crawler → enrich → filter_images → generate_report → output_report
 抓列表    补全README    下载+识图       生成分类正文        写入 reports/
```

基于 [LangGraph](https://github.com/langchain-ai/langgraph) 编排，节点代码见 `src/graph/nodes/`。

## 🚀 快速开始

```bash
# 1. 安装依赖（使用 uv）
uv sync

# 2. 配置环境变量
cp .env.example .env                  # 然后填入 OPENAI_API_KEY

# 3. 运行
uv run python src/main.py
```

每期周刊在独立的日期文件夹里：`reports/YYYY_MM_DD/README.md`，配图在同目录 `reports/YYYY_MM_DD/assets/`。

> 未配置 `OPENAI_API_KEY` 时会直接跳过、不执行后续步骤。
>
> 本地反复运行建议在 `.env` 配上 `GITHUB_TOKEN`，否则 GitHub 未认证 API 仅 60 次/小时，容易限流导致 README/配图抓不全。

## ⚙️ 环境变量

| 变量 | 必填 | 默认 | 说明 |
|------|:---:|------|------|
| `OPENAI_API_KEY` | ✅ | — | OpenAI（或兼容服务）密钥 |
| `OPENAI_MODEL` | | `gpt-4o` | 模型名（需支持视觉） |
| `OPENAI_BASE_URL` | | 官方 | 走代理 / 自建网关 / 兼容服务时填 |
| `README_MAX_CHARS` | | `32000` | README 截断长度（字符） |
| `WEEKLY_CONCURRENCY` | | `8` | 并行处理仓库的并发数 |
| `CACHE_TTL_DAYS` | | `30` | 本地缓存有效期（天），超期自动清理 |
| `GITHUB_TOKEN` | | — | 提高 GitHub API 速率限制（CI 自动注入，本地建议配） |

> 也可接入任意 OpenAI 兼容的视觉模型。例如使用小米 MiMo：
> `OPENAI_BASE_URL=https://api.xiaomimimo.com/v1`、`OPENAI_MODEL=mimo-v2.5`，
> `OPENAI_API_KEY` 填 MiMo 的 key 即可。

## 🤖 CI

`.github/workflows/weekly.yml` 每周一 00:00 UTC 自动运行（也支持手动触发）。
使用前在仓库 **Settings → Secrets** 配置 `OPENAI_API_KEY`，生成后会自动 commit 回仓库。

## 📄 文档

- 产品需求文档：[`docs/PRD.md`](./docs/PRD.md)

## License

[MIT](./LICENSE) © 2026 yliu
