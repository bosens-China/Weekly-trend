# 📰 GitHub 一周热点周刊

> 每周自动抓取 [GitHub Trending（本周）](https://github.com/trending?since=weekly)，借助 LLM 整理成一份分类、带图的**中文周刊**。

[![Weekly Report](https://github.com/bosens-China/Weekly-trend/actions/workflows/weekly.yml/badge.svg)](https://github.com/bosens-China/Weekly-trend/actions/workflows/weekly.yml)
[![RSS](https://img.shields.io/badge/RSS-订阅-orange?logo=rss)](https://raw.githubusercontent.com/bosens-China/Weekly-trend/master/feed.xml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

## 🧐 这是什么

一条全自动的「GitHub Trending → 中文周刊」流水线：抓取本周热门仓库，补全 README、配图与项目信息，再由 LLM 按主题分类、生成中文正文，每周归档为「第 N 期」。

每期周刊在 `reports/YYYY_MM_DD/README.md`，配图在同目录 `assets/`。

## 📰 往期周刊

<!-- ISSUES:START -->
| 期号 | 日期 | 收录项目 | 链接 |
| :--: | :--: | :--: | :-- |
| 第 6 期 | 2026-07-27 | 23 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_07_27/README.md) |
| 第 5 期 | 2026-07-20 | 14 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_07_20/README.md) |
| 第 4 期 | 2026-07-13 | 21 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_07_13/README.md) |
| 第 3 期 | 2026-07-06 | 21 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_07_06/README.md) |
| 第 2 期 | 2026-06-29 | 21 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_06_29/README.md) |
| 第 1 期 | 2026-06-22 | 19 个 | [阅读](https://github.com/bosens-China/Weekly-trend/blob/master/reports/2026_06_22/README.md) |
<!-- ISSUES:END -->

## 📡 订阅（RSS）

把下面的地址加进 RSS 阅读器，每出一期都会推送：

```
https://raw.githubusercontent.com/bosens-China/Weekly-trend/master/feed.xml
```

## 开发与提交

首次拉取仓库后执行 `pnpm install --frozen-lockfile`。安装过程会启用 Husky 的 Git 钩子；每次提交前，钩子会仅格式化并检查已暂存的 Python 文件，格式化结果会自动加入本次提交。

需要手动格式化整个仓库时，运行 `pnpm format`；运行 Ruff 静态检查使用 `pnpm lint`；运行 Python 类型检查使用 `pnpm typecheck`。本地开发需要 Git、Node.js 22.22.1 或更高版本、pnpm，以及 uv。

需要验证真实抓取与 LLM 报告链路时，配置 `.env` 后运行 `uv run python scripts/smoke_single.py`。该脚本只处理一个仓库并打印结果，不会写入正式周刊。

> Git 的 `post-commit` 钩子无法修改已经创建的提交，因此这里使用 `pre-commit` 钩子，以确保提交中的代码本身已格式化。

## License

[MIT](./LICENSE) © 2026 yliu
