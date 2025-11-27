# Story 1.1: 通过环境变量配置 OpenAI 协议 LLM 提供商

Status: done

## Story

As a power user or DevOps engineer,
I want to configure the OpenAI-compatible LLM provider via environment variables (base_url, api_key, model, type),
So that I can switch between OpenRouter, OpenAI, and self-hosted gateways without changing code.

该故事的目标是：在不修改业务层调用 LLM 的代码前提下，通过一组环境变量完成 LLM 提供商的选择与切换，使 Bot 与回测都可以透明地接入任意兼容 OpenAI Chat Completions 的服务。

## Acceptance Criteria

1. 当正确设置如下环境变量：
   - `LLM_API_BASE_URL`
   - `LLM_API_KEY`
   - `TRADEBOT_LLM_MODEL`（或等价配置项）
   并运行 `bot.py` 主循环若干轮后：
   - 所有 LLM 请求均发送到 `LLM_API_BASE_URL` 对应的 OpenAI 协议兼容端点；
   - 返回结果被正常解析为 JSON，并写入 `ai_decisions.csv` 与 `ai_messages.csv`；
   - 不需要修改任何调用 LLM 的业务代码（调用方代码仅依赖统一客户端接口）。

2. 在以下三种典型场景下，仅通过调整环境变量即可完成 LLM 提供商切换，无需改动源代码：
   - 使用 OpenRouter 作为默认 LLM 入口；
   - 使用官方 OpenAI 或其他公开的 OpenAI-compatible 服务；
   - 使用本地或自建的 OpenAI-compatible 网关（如 `http://localhost:8000/v1`）。

3. 文档与配置示例已更新：
   - `.env.example` 中新增一段示例配置片段，分别展示 OpenRouter / OpenAI / 自建网关 三种常见配置方式；
   - 相关文档中（例如 `README` 或配置章节）补充了对上述环境变量的说明与示例用法，并与 PRD/架构文档保持一致。

## Tasks / Subtasks

- [x] 任务 1：设计统一的 OpenAI 协议 LLM 配置层（AC: #1, #2）
  - [x] 从现有环境变量与 PRD 要求出发，梳理当前 LLM 相关配置（如 `OPENROUTER_API_KEY`、`TRADEBOT_LLM_MODEL` 等），确认与新变量的映射关系。
  - [x] 定义读取 `LLM_API_BASE_URL`、`LLM_API_KEY`、`TRADEBOT_LLM_MODEL` 等环境变量的配置结构，并为缺失配置提供明确的错误信息或安全默认值。
  - [x] 确保配置层同时适用于 live 模式与 backtest（遵守现有 BACKTEST_* 覆盖模式），避免引入第二套配置通道。

- [x] 任务 2：实现 OpenAI 协议统一客户端抽象（AC: #1, #2）
  - [x] 在合适的位置新增一个面向 OpenAI Chat Completions 的客户端抽象（例如 `OpenAICompatibleClient` 或等价接口），只暴露统一的 "chat_completion" 调用入口。
  - [x] 客户端内部根据配置构造 HTTP 请求，指向 `LLM_API_BASE_URL`，并以提供商要求的方式携带 API Key，处理基础错误与重试。
  - [x] 确保客户端的返回值结构与当前 Bot 期望的 JSON 格式兼容，不破坏既有决策解析与 CSV 写入逻辑。

- [x] 任务 3：在 `bot.py` 中接入统一客户端并清理耦合（AC: #1, #2）
  - [x] 梳理 `bot.py` 中所有直接或间接调用 LLM 的位置，统一改用新客户端抽象，而非特定于 OpenRouter 的调用方式。
  - [x] 核对现有日志与错误处理逻辑，确保在 LLM 请求失败时仍有清晰的错误输出（与 PRD 中可观测性要求一致）。
  - [x] 在非配置正确或网络异常的情况下，保持既有的降级/重试行为，不因为切换客户端而降低稳定性。

- [x] 任务 4：配置示例与文档更新（AC: #2, #3）
  - [x] 在 `.env.example` 中新增一段示例配置，分别展示：
    - [x] 使用 OpenRouter 的典型配置；
    - [x] 使用官方 OpenAI 的典型配置；
    - [x] 使用本地 / 自建 OpenAI-compatible 网关的典型配置（例如 `http://localhost:8000/v1`）。
  - [x] 在相关文档中补充说明上述环境变量的含义、取值示例以及与现有配置项（如 `TRADEBOT_LLM_MODEL`）的关系。
  - [x] 检查 PRD 与架构文档中对 LLM 提供商与配置方式的描述，必要时补充一句说明「支持任意 OpenAI 协议兼容 LLM 提供商」。

- [x] 任务 5：回归验证与最小回测（AC: #1, #2）
  - [x] 分别在三种典型配置下运行 `bot.py` 若干轮，确认 LLM 请求全部发往预期的 `LLM_API_BASE_URL`，并能成功写入 `ai_decisions.csv` / `ai_messages.csv`。
  - [x] 使用至少一种配置运行一次典型 `backtest.py`（小时间窗），确认回测通路同样受新配置控制且行为合理。
  - [x] 记录在不同配置下的关键行为差异（如延迟、错误情况），用于后续扩展 Story（例如多提供商性能对比）。

## Dev Notes

- 实现需严格遵守现有架构中关于「外部服务集成与配置」的模式：
  - 参考 `docs/architecture/04-integrations.md` 中对 OpenRouter/DeepSeek、Hyperliquid、Telegram 等外部依赖的统一描述；
  - 参考 `docs/architecture/07-implementation-patterns.md` 中「位置模式」「配置与密钥」部分，确保所有新环境变量只通过 `.env` / 运行环境注入，而不写入代码库。
- 与 PRD 中的映射关系：
  - 本 Story 主要支撑 PRD 第 4.3 节「LLM 配置与 Prompt 管理」中「可插拔 LLM 与配置」的目标，尤其是通过环境变量切换模型与提供商的能力；
  - 也与非功能需求中「安全性」「可观测性」相关——必须在配置错误或网络异常时给出清晰日志，而不是静默失败。
- 实现过程中，应避免在 `bot.py` 中散落新的硬编码 URL 或 provider 逻辑，尽量将所有差异收敛在配置层与统一客户端抽象中。

### Project Structure Notes

- 相关核心文件与目录：
  - 交易主循环与 LLM 调用：`bot.py`；
  - 回测入口：`backtest.py`；
  - 环境变量示例：`.env.example`；
  - 产品需求：`docs/prd.md`（特别是 4.3 小节「LLM 配置与 Prompt 管理」）；
  - 架构与实现模式：`docs/architecture/` 下的各分片文档，尤其是 `06-project-structure-and-mapping.md` 与 `07-implementation-patterns.md`。
- 新增的 OpenAI 协议客户端实现建议放置在靠近 `bot.py` 的位置（如独立模块），并在架构文档后续更新中补充一条「外部服务适配层」说明，保持项目结构的可阅读性。

### References

- Epics：`docs/epics.md` 中的「Story 1.1: 通过环境变量配置 OpenAI 协议 LLM 提供商」章节（包含原始故事描述与验收标准草稿）。
- PRD：`docs/prd.md` 第 4.3 节「LLM 配置与 Prompt 管理」及相关非功能需求章节。
- 架构：
  - `docs/architecture/04-integrations.md`（外部依赖与集成点总览）；
  - `docs/architecture/06-project-structure-and-mapping.md`（PRD 功能块到源码结构的映射）；
  - `docs/architecture/07-implementation-patterns.md`（实现模式、配置与密钥、外部服务集成约定）。

## Dev Agent Record

### Context Reference

- Story Context: `docs/sprint-artifacts/1-1-configure-openai-llm-provider-via-env.context.xml`

### Agent Model Used

- （由实际实现本故事的开发 Agent 在完成后填写，例如具体使用的模型与版本。）

### Debug Log References

- （在开发与测试过程中，如引入新的日志前缀或关键日志位置，请在此简要记录，便于后续排查。）

### Completion Notes List

- （实现完成后，由开发者总结关键实现决策、风险与后续建议。）

### File List

- （实现完成后，由开发者列出新增 / 修改 / 删除的文件及其用途，用于后续故事的衔接与复用。）

## Change Log

- [ ] 2025-11-26：初始 Story 草稿由 Scrum Master 根据 epics/PRD/架构文档生成，状态设为 `drafted`。
- [x] 2025-11-26：Story 1.1 实现完成（统一 LLM 配置层与 OpenAI-compatible 客户端，更新 bot.py / backtest.py / .env.example），状态设为 `done`。
