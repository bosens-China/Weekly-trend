# GitHub 一周热点 · 第 1 期

> 📅 2026-06-22 ｜ 数据来源：GitHub Trending（本周）

---

## AI 代理与工具

### [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)
⭐ 总 star 10,292 | 🔥 本周 star 6,372 | 💻 C
一个高性能代码智能 MCP 服务器。它能将代码库索引为持久化的知识图谱，支持 158 种语言，平均索引时间在毫秒级，查询延迟低于 1 毫秒，并声称能将 token 消耗减少 99%。项目打包为单个静态二进制文件，零依赖，可直接用于 Claude Code、Cursor 等 11 种编程代理。
![](assets/DeusData__codebase-memory-mcp__0.png)
🔗 官网：https://deusdata.github.io/codebase-memory-mcp/
`#aider` `#claude-code` `#cursor` `#mcp-server` `#knowledge-graph`

### [chopratejas/headroom](https://github.com/chopratejas/headroom)
⭐ 总 star 44,431 | 🔥 本周 star 16,102 | 💻 Python
一个为 AI 代理设计的上下文压缩层。它在数据（包括工具输出、日志、RAG 块和对话历史）发送给 LLM 之前进行压缩，号称能在保持答案质量的前提下将 token 消耗减少 60% 到 95%。提供了库、代理、MCP 服务器等多种集成方式，并支持可逆压缩。
![](assets/chopratejas__headroom__0.gif)
🔗 官网：https://headroom-docs.vercel.app/docs
`#llm` `#mcp` `#token-optimization` `#context-engineering`

### [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach)
⭐ 总 star 36,873 | 🔥 本周 star 8,233 | 💻 Python
为你的 AI 代理一键接入互联网能力。项目通过统一的命令行工具集成了 Twitter、Reddit、YouTube、GitHub、B站、小红书等多个平台的读取和搜索功能，旨在让任何能运行 Shell 命令的 AI 代理（如 Claude Code、Cursor）都能轻松获取网络信息，且大部分功能免费。
`#ai-agent` `#web-scraper` `#mcp` `#free-api`

### [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector)
⭐ 总 star 9,031 | 🔥 本周 star 4,055 | 💻 Python
一个针对 AI 代理技能的安全扫描器。它能在安装技能（用于 Claude Code、Codex CLI 等）之前检测其中的漏洞、恶意模式和安全风险，提供 64 种漏洞模式的检测，并生成风险评分和报告，支持终端、JSON、Markdown 等多种输出格式。
`#security` `#ai-agent` `#llm`

### [asgeirtj/system_prompts_leaks](https://github.com/asgeirtj/system_prompts_leaks)
⭐ 总 star 44,403 | 🔥 本周 star 1,984 | 💻 JavaScript
收集了各大 AI 聊天机器人（如 Claude、ChatGPT、Gemini、Grok 等）的系统提示词（System Prompt）。该项目旨在文档化和公开这些通常隐藏的指令，帮助用户理解 AI 的行为规则，并会随着新模型的发布而定期更新。
![](assets/asgeirtj__system_prompts_leaks__0.png)
`#prompt-engineering` `#claude` `#chatgpt` `#llm`

### [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage)
⭐ 总 star 8,763 | 🔥 本周 star 2,867 | 💻 Python
首个开源的代理式视频制作系统。它通过将你的 AI 编程助手转变为一个完整的视频工作室，支持从概念研究、脚本编写、素材生成到编辑合成的全流程。提供 12 种制作流水线、52 个工具和 500 多个代理技能，能够利用免费素材和 AI 生成技术制作真实的视频。
`#agentic-ai` `#video-production` `#open-source`

### [withastro/flue](https://github.com/withastro/flue)
⭐ 总 star 6,298 | 🔥 本周 star 1,272 | 💻 TypeScript
一个沙箱代理框架（Agent Harness Framework）。它提供可编程的 TypeScript 运行环境，用于构建自主代理和强大的 AI 工作流，支持会话、工具、技能、指令、文件系统访问以及安全的沙箱环境。
`#agent` `#framework`

### [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
⭐ 总 star 64,770 | 🔥 本周 star 5,610 | 💻 Shell
一套面向 AI 编程代理的生产级工程技能集合。这些技能将高级工程师在软件开发各阶段（定义、规划、构建、验证、审查、发布）使用的最佳实践、质量门控和工作流编码化，让 AI 代理能够像资深工程师一样一致地执行开发任务。
![](assets/addyosmani__agent-skills__0.jpg)
`#agent-skills` `#claude-code` `#cursor`

### [LMCache/LMCache](https://github.com/LMCache/LMCache)
⭐ 总 star 9,543 | 🔥 本周 star 506 | 💻 Python
一个用于可扩展 LLM 推理的 KV 缓存管理中间层。它将 KV 缓存从临时状态转变为可持久化、可跨引擎复用、可监控和可转换的“AI 原生知识”，从而减少首 token 延迟（TTFT）并提高吞吐量，特别适用于长上下文、多轮对话和 RAG 等场景。
![](assets/LMCache__LMCache__0.png)
🔗 官网：https://lmcache.ai/
`#llm` `#inference` `#kv-cache` `#vllm`

## 开发者工具

### [n0-computer/iroh](https://github.com/n0-computer/iroh)
⭐ 总 star 10,451 | 🔥 本周 star 1,712 | 💻 Rust
一个基于 Rust 的模块化网络栈。它通过公钥而非 IP 地址进行连接，自动寻找并维持最快的连接路径，包括打洞直连和使用公共中继服务器。构建在 QUIC 之上，并提供了 blob 传输、发布-订阅网络等预构建协议。
`#rust` `#p2p` `#quic` `#networking`

### [google-research/timesfm](https://github.com/google-research/timesfm)
⭐ 总 star 24,889 | 🔥 本周 star 4,114 | 💻 Python
由 Google Research 开发的预训练时间序列基础模型，用于时间序列预测。最新版本 TimesFM 2.5 支持最长 16k 的上下文长度和连续分位数预测，并已集成到 BigQuery ML 和 Google Sheets 等 Google 产品中。
🔗 官网：https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
`#time-series` `#forecasting` `#foundation-model`

### [Kong/insomnia](https://github.com/Kong/insomnia)
⭐ 总 star 39,513 | 🔥 本周 star 1,006 | 💻 TypeScript
一款开源的、跨平台的 API 客户端，支持 GraphQL、REST、WebSockets、SSE、gRPC 等协议。提供 API 调试、设计、测试、模拟和协作等功能，并支持本地、Git 和云存储。
![](assets/Kong__insomnia__0.png)
🔗 官网：https://insomnia.rest
`#api-client` `#graphql` `#rest-api`

### [tursodatabase/turso](https://github.com/tursodatabase/turso)
⭐ 总 star 20,807 | 🔥 本周 star 1,390 | 💻 Rust
一个用 Rust 编写的、兼容 SQLite 的进程内 SQL 数据库。它在保持 SQLite 兼容性的同时，引入了 `BEGIN CONCURRENT`、变更数据捕获、多语言绑定（包括 WebAssembly）等特性，旨在成为 SQLite 的下一代演进方向。
![](assets/tursodatabase__turso__0.png)
`#database` `#sqlite` `#rust` `#embedded-database`

### [swc-project/swc](https://github.com/swc-project/swc)
⭐ 总 star 34,107 | 🔥 本周 star 403 | 💻 Rust
一个基于 Rust 构建的超快 TypeScript/JavaScript 编译器。它作为一个库同时支持 Rust 和 JavaScript，旨在让 Web 开发变得更快，并能作为 Babel 等工具的替代方案。
![](assets/swc-project__swc__0.png)
🔗 官网：https://swc.rs
`#typescript` `#compiler` `#rust`

### [iptv-org/iptv](https://github.com/iptv-org/iptv)
⭐ 总 star 127,133 | 🔥 本周 star 7,266 | 💻 TypeScript
一个收集全球公开可用 IPTV 频道的项目。它提供包含所有频道的主播放列表以及分类播放列表，用户只需将链接粘贴到支持直播流的播放器中即可观看。
![](assets/iptv-org__iptv__0.png)
🔗 官网：https://iptv-org.github.io
`#iptv` `#m3u` `#tv`

## 项目管理

### [makeplane/plane](https://github.com/makeplane/plane)
⭐ 总 star 52,348 | 🔥 本周 star 1,514 | 💻 TypeScript
一个开源的项目管理平台，旨在成为 Jira、Linear、Monday 等工具的替代品。支持管理任务、迭代周期、模块和产品路线图，提供丰富视图和分析功能，并支持 Docker 和 Kubernetes 自托管部署。
![](assets/makeplane__plane__0.png)
🔗 官网：http://plane.so
`#project-management` `#jira-alternative` `#kanban`

### [chatwoot/chatwoot](https://github.com/chatwoot/chatwoot)
⭐ 总 star 33,121 | 🔥 本周 star 2,036 | 💻 Ruby
一个开源的现代客户支持平台，可替代 Intercom、Zendesk 等。它提供全渠道客服支持，将网页聊天、邮件、Facebook、WhatsApp 等对话集中到一个收件箱，并内置了 AI 代理（Captain）、帮助中心等功能。
![](assets/chatwoot__chatwoot__0.png)
🔗 官网：https://www.chatwoot.com/help-center
`#customer-support` `#livechat` `#omnichannel`

## 基础设施与云原生

### [meshery/meshery](https://github.com/meshery/meshery)
⭐ 总 star 11,224 | 🔥 本周 star 921 | 💻 TypeScript
一个云原生管理平台，是 CNCF 的项目。它作为一个自助式工程平台，支持可视化、协作式的 GitOps 方式来设计和管理所有基于 Kubernetes 的多云基础设施和应用，提供生命周期管理、性能表征等功能。
![](assets/meshery__meshery__3.png)
🔗 官网：https://meshery.io
`#cloud-native` `#kubernetes` `#gitops` `#cncf`

## 教育与学习

### [freeCodeCamp/freeCodeCamp](https://github.com/freeCodeCamp/freeCodeCamp)
⭐ 总 star 450,076 | 🔥 本周 star 3,294 | 💻 TypeScript
freeCodeCamp.org 的开源代码库和课程。这是一个免费的编程学习社区，提供全栈 Web 开发和机器学习课程，通过互动编程挑战帮助用户学习数学、编程和计算机科学，并提供免费的开发者认证。
![](assets/freeCodeCamp__freeCodeCamp__0.png)
🔗 官网：https://contribute.freecodecamp.org
`#learn-to-code` `#javascript` `#react` `#curriculum`
