# LLM-trader-test - Epic Breakdown

**Author:** Nick  
**Date:** 2025-11-26  
**Project Level:** trading-bot  
**Target Scale:** single-team

---

## Overview

本文件基于现有 `docs/prd.md` 的 MVP 功能，新增对后续工作重点的 Epic 分解，当前包含以下重点 Epic：

- Epic 1：支持通过统一的 OpenAI 协议客户端访问任意兼容的 LLM 提供商（包括 OpenRouter、官方 OpenAI、自建 OpenAI-compatible 网关等）。
- Epic 6：统一交易所执行层 & 多交易所可插拔支持（在不同交易所 backend 间保持一致的实盘执行体验）。

> 说明：本文件是活文档，后续可以继续追加更多 Epic 与对应 User Stories。

---

## Functional Requirements Inventory

- **FR-L1：统一的 OpenAI 协议 LLM 访问能力**  
  系统应通过一层通用的 OpenAI Chat Completions 客户端访问 LLM，只要对方提供兼容的 HTTP 接口即可；具体供应商（OpenRouter、OpenAI、自建网关等）通过配置而非代码决定。

- **FR13：统一交易所执行抽象层（Exchange Execution Layer）**  
  系统应提供一层与具体交易所无关的实盘执行抽象，使 Bot 在开仓、平仓、附带 SL/TP、错误反馈等行为上，对 Binance、Hyperliquid 以及未来新增交易所保持一致的用户体验。

---

## FR Coverage Map

- FR-L1 由 **Epic 1：支持任意 OpenAI 协议兼容 LLM 提供商** 覆盖，后续可以根据需要增加更多 Story 细化实现路径。

---

## Epic 1: 支持任意 OpenAI 协议兼容 LLM 提供商

### Epic 1 概述

**背景 / 问题**

- 当前系统仅通过 `OPENROUTER_API_KEY` 访问 LLM，实际依赖 OpenRouter 作为唯一入口。
- 市面上越来越多 LLM 服务提供「OpenAI 协议兼容」的 API（官方 OpenAI、DeepSeek 自建网关、本地 vLLM / OpenAI-compatible proxy 等）。
- 单一依赖 OpenRouter 带来成本、稳定性、合规和可迁移性方面的限制。

**目标**

- 为 Bot、回测以及相关脚本提供一层**统一的 OpenAI 协议 LLM 客户端**：
  - 只要服务支持 OpenAI Chat Completions 风格接口（如 `/v1/chat/completions`），就可以通过配置直接接入。
- 通过环境变量完成不同 LLM 提供商的切换，无需修改代码。
- 在不破坏现有 OpenRouter 工作方式的前提下，保留 OpenRouter 作为一种默认/可选后端。

**范围（In Scope）**

- 抽象出通用 LLM 客户端：支持 `base_url`、`api_key`、`model`、超时与重试策略配置。
- 使用环境变量控制 LLM 访问配置，例如（具体命名可在实现时细化）：
  - `LLM_API_BASE_URL`：OpenAI 协议兼容服务 base URL。
  - `LLM_API_KEY`：通用 API Key（与 `OPENROUTER_API_KEY` 兼容或提供迁移路径）。
  - `LLM_API_TYPE`：可选标识（如 `openrouter` / `openai` / `custom`），用于处理少量差异化 header。
- Bot 主循环、回测等统一改用该客户端，而不是直接依赖 OpenRouter 特定调用方式。
- 文档更新：
  - 在 PRD 的 LLM 配置章节中，明确说明支持任意 OpenAI 协议兼容 LLM 提供商（规划中）。
  - 在 README / 配置说明中给出如何切换到自建 OpenAI-compatible 网关的示例。

**非范围（Out of Scope）**

- 不为每个第三方提供商单独设计 UI 级或脚本级「专属配置向导」。
- 不保证兼容所有**非标准** OpenAI 协议变种（参数和路径完全自定义的接口）。
- 不在本 Epic 内实现「多提供商智能路由 / 负载均衡 / 流量分配」等高级能力（可作为后续独立 Epic）。

**验收标准（Done Criteria）**

1. 在下列三种场景中，仅通过环境变量即可完成切换，无需修改代码：
   - a. 使用 OpenRouter 作为 LLM 入口（保持当前默认行为）。
   - b. 使用官方 OpenAI 或其他公开 OpenAI-compatible 服务。
   - c. 使用本地或自建 OpenAI-compatible 网关（例如 `http://localhost:8000/v1`）。
2. 在上述三种场景中：
   - Bot 主循环能稳定完成多轮调用，`ai_decisions.csv` 与 `ai_messages.csv` 中有成功记录。
   - `backtest.py` 能在三种后端间切换运行并正常产出结果文件。
3. 当配置错误（base URL 不可达 / Key 无效等）时：
   - 有清晰错误日志，明确指出是「LLM 后端配置/连接问题」。
   - Bot 不会异常退出主循环，而是按既有错误策略记录并重试或优雅降级。
4. 文档层面：
   - 有简要文档说明如何通过 `.env` 配置不同类型 LLM 提供商。

---

### Story 1.1: 通过环境变量配置 OpenAI 协议 LLM 提供商

As a power user or DevOps engineer,  
I want to configure the OpenAI-compatible LLM provider via environment variables (base_url, api_key, model, type),  
So that I can switch between OpenRouter, OpenAI, and self-hosted gateways without changing code.

**Acceptance Criteria:**

- Given 已正确设置如下环境变量：
  - `LLM_API_BASE_URL`
  - `LLM_API_KEY`
  - `TRADEBOT_LLM_MODEL`（或等价配置）
- When 运行 `bot.py` 主循环若干轮次
- Then 所有 LLM 请求均发送到 `LLM_API_BASE_URL`，并且：
  - 返回结果被正常解析为 JSON，并写入 `ai_decisions.csv` / `ai_messages.csv`；
  - 不需要修改任何调用 LLM 的业务代码。

**And**：

- 更新一份示例 `.env` 片段，展示三种典型配置：OpenRouter / OpenAI / 自建网关。

**Prerequisites:**

- 现有基于 `OPENROUTER_API_KEY` 的 LLM 调用路径已在当前环境下可用。

**Technical Notes:**

- 推荐在代码中封装一个 `OpenAICompatibleClient` 或等价抽象：
  - 内部持有 base_url、api_key、model 等配置；
  - 统一处理 header、超时与错误重试逻辑；
  - 对调用方暴露统一的 "chat_completion" 接口。  
- 需要注意部分提供商对扩展字段（如 `thinking`、`metadata` 等）的兼容性差异，必要时做降级或条件发送。

---

## Epic 6: 统一交易所执行层 & 多交易所可插拔支持

### Epic 6 概述

**背景 / 问题**

- 当前 Bot 在 Hyperliquid 与 Binance Futures 上的实盘行为不一致：
  - Hyperliquid 通过 `HyperliquidTradingClient` 封装了杠杆、tick size、SL/TP 触发单等细节；
  - Binance Futures 直接调用 ccxt 的 `create_order`，SL/TP 主要由 Bot 自己用 K 线极值模拟执行；
  - 错误模型与返回结构也不统一。

**目标**

- 为 Bot 提供一层与具体交易所无关的统一执行接口（ExchangeClient 抽象）：
  - 开仓 / 平仓 /（可选）附带 SL/TP 的调用方式一致；
  - 对不同 backend（Binance / Hyperliquid / 未来交易所）返回统一的结果结构与错误语义；
  - 在用户体验层面保证「不管接在哪个交易所，风险护栏与执行行为感知是一致的」。

**范围（In Scope）**

- 定义 `ExchangeClient` 抽象接口和统一结果结构（EntryResult / CloseResult）。
- 为 Hyperliquid 与 Binance Futures 提供该接口的适配实现。
- 在 `execute_entry` / `execute_close` 等核心路径中迁移到统一抽象，而不是直接分支调用具体交易所 SDK。
- 在配置与文档层面统一 `TRADING_BACKEND` 与实盘开关的语义，为未来新增交易所留扩展点。

**非范围（Out of Scope）**

- 不强制所有交易所一开始就支持原生 SL/TP 触发单；在 Binance 上仍允许由 Bot 侧 `check_stop_loss_take_profit` 负责执行保护。
- 不在本 Epic 内实现智能多交易所路由、流动性聚合等高级功能（可作为后续独立 Epic）。

**验收标准（Done Criteria）**

1. Bot 在选择 Hyperliquid 或 Binance Futures 作为 backend 时，开仓 / 平仓 的调用方式完全一致（同一组参数结构），且返回结果结构统一。
2. 对于常见错误（如余额不足、下单被拒、连接失败），不同 backend 通过统一字段暴露可用于日志与告警的信息。
3. 新增交易所时，只需实现 ExchangeClient 接口及少量配置，即可被 Bot 主循环复用，而无需修改策略/风险控制层逻辑。

---

### Story 6.1: 定义 ExchangeClient 抽象接口与统一结果结构

As a developer working on this trading bot,  
I want a single, exchange-agnostic execution interface (ExchangeClient) with unified Entry/Close result shapes,  
So that the bot and strategy code do not care which concrete exchange backend is used.

**Acceptance Criteria:**

- 定义一个清晰的 ExchangeClient 抽象（协议 / 基类 / 接口），至少包含：
  - `place_entry(...)`：接收 coin/symbol、side、size、entry_price、stop_loss_price、take_profit_price、leverage、liquidity 等参数；
  - `close_position(...)`：接收 coin/symbol、side、size（可选）、fallback_price 等参数。
- 定义统一的返回结构（EntryResult / CloseResult），至少包含：
  - `success: bool`、`backend: str`、`errors: list[str]`；
  - 可选的 `entry_oid` / `tp_oid` / `sl_oid` / `close_oid` 字段；
  - `raw` 字段保存原始交易所响应，用于 debug。
- 在实现层面暂不改变任何实盘行为，只引入接口与类型定义，现有调用仍然工作正常（可通过测试或最小验证脚本确认）。

**Prerequisites:**

- 对当前 Hyperliquid 与 Binance Futures 执行路径已有基本理解。

---

### Story 6.2: 为 Hyperliquid 提供 ExchangeClient 适配器

As a developer maintaining Hyperliquid live trading,  
I want HyperliquidTradingClient to be wrapped behind the unified ExchangeClient interface,  
So that Hyperliquid live execution can be used transparently by the bot.

**Acceptance Criteria:**

- 实现 `HyperliquidExchangeClient` 或等价适配器，实现 ExchangeClient 接口：
  - `place_entry(...)` 内部调用 `HyperliquidTradingClient.place_entry_with_sl_tp`；
  - `close_position(...)` 内部调用 `HyperliquidTradingClient.close_position`。
- 将 Hyperliquid 原始响应映射到统一的 EntryResult / CloseResult 结构：
  - 填充 `backend="hyperliquid"`，并尽量解析出 `entry_oid` / `tp_oid` / `sl_oid` / `close_oid`；
  - 对错误与拒单写入统一的 `errors` 字段，同时保留 `raw`。
- 保证现有 Hyperliquid 行为不变：
  - 仍然使用具备 tick size 归一化与触发单支持的实现；
  - 在 `hyperliquid_trader.is_live` 的判断与日志语义上保持一致。

---

### Story 6.3: 为 Binance Futures 提供 ExchangeClient 适配器

As a developer adding multi-exchange support,  
I want Binance Futures live trading to be accessed via the same ExchangeClient abstraction,  
So that the bot call-site does not need Binance-specific branching.

**Acceptance Criteria:**

- 实现 `BinanceFuturesExchangeClient` 或等价适配器，实现 ExchangeClient 接口：
  - `place_entry(...)` 内部使用 ccxt `create_order` 下市价单，并在可能情况下设置杠杆；
  - `close_position(...)` 使用 reduce-only 市价单平仓。
- 明确当前阶段行为：
  - SL/TP 仍主要由 Bot 侧逻辑负责（如 `check_stop_loss_take_profit`），但接口仍接受 SL/TP 参数，为未来使用交易所原生触发单留口；
  - 对常见错误（API key 缺失、初始化失败、下单异常）统一写入 EntryResult / CloseResult 的 `errors` 字段。
- 在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时，通过 ExchangeClient 完成与现有逻辑等价的实盘操作（至少覆盖开仓与全仓平仓路径）。

---

### Story 6.4: 将 execute_entry / execute_close 重构为使用 ExchangeClient

As a maintainer of the main trading loop,  
I want execute_entry and execute_close to depend only on ExchangeClient,  
So that adding or changing exchanges does not require editing core bot logic.

**Acceptance Criteria:**

- 在 `execute_entry` / `execute_close` 中，用一个选定好的 `exchange_client` 实例替代当前针对 Hyperliquid / Binance 的 if/elif 分支：
  - 根据 `TRADING_BACKEND` 与实盘开关构造或选择具体的 ExchangeClient 实现；
  - 对 EntryResult / CloseResult 中的 `success` / `errors` / OID 字段进行统一处理，并写入持仓结构。
- 现有的持仓结构中，增加或规范字段以记录 live 信息（如 `live_backend`、`entry_oid`、`tp_oid`、`sl_oid`），并对 Hyperliquid 路径保持向后兼容。
- 回归测试：
  - 在仅 paper 模式下，行为保持不变；
  - 在 Hyperliquid live 开启时，订单与日志行为与重构前等价（允许日志文案略有调整）。

---

### Story 6.5: 统一配置语义并为未来交易所留扩展点

As a power user or infra engineer,  
I want a consistent configuration model for selecting trading backends and enabling live mode,  
So that switching or adding exchanges is predictable and low-risk.

**Acceptance Criteria:**

- 在配置与 README 中，明确 `TRADING_BACKEND`、各交易所 API key、live 开关变量的含义与组合：
  - 例如 `TRADING_BACKEND=hyperliquid | binance_futures | <future>`；
  - 对 Hyperliquid 与 Binance 分别说明需要哪些环境变量与安全注意事项。
- 为未来新增交易所定义最小接入规范：
  - 必须实现 ExchangeClient 接口；
  - 必须在配置与文档中声明 backend 名称与所需环境变量；
  - 必须符合统一的 EntryResult / CloseResult 错误语义。
- 文档中补充一小节「如何新增一个交易所适配器」，以 Story 级别的 checklist 形式给出步骤。

#### 如何新增一个交易所适配器（Story 级别 Checklist）

当你需要为未来的交易所提供实盘/纸上执行能力时，建议遵循以下最小接入规范：

1. **约定 backend 标识（TRADING_BACKEND 值）**
   - 选择一个新的字符串，例如：`my_exchange`，并在文档中说明：
     - `TRADING_BACKEND=my_exchange` 代表「打算使用 my_exchange 作为执行后端」。

2. **在 `.env.example` 中补充该 backend 所需环境变量**
   - 至少包括：
     - 一个显式的 live 开关（例如 `MY_EXCHANGE_LIVE_TRADING=false`）。
     - 访问该交易所所需的 API Key / Secret / 资金规模等字段。
   - 用简短注释说明：
     - 默认行为（建议保持 `false` / 纸上交易）。
     - 打开 live 后会发送真实订单，需要自担风险。

3. **实现 `ExchangeClient` 接口**
   - 在 `exchange_client.py` 中新增适配器类，例如 `MyExchangeClient`：
     - 实现 `place_entry(...) -> EntryResult` 与 `close_position(...) -> CloseResult`。
     - `backend` 字段固定为你的标识（如 `"my_exchange"`）。
     - 统一填充：`success: bool`、`errors: list[str]`、可用时的 `entry_oid` / `tp_oid` / `sl_oid` / `close_oid`，以及 `raw` 原始响应。

4. **在 `get_exchange_client` 工厂中挂接**
   - 在 `get_exchange_client(backend: str, **kwargs)` 中，为新的 backend 分支返回你的适配器实例：
     - 校验必要依赖（底层 SDK / ccxt 实例等）是否通过 `kwargs` 传入。
     - 缺失依赖时抛出清晰的 `ValueError`，而不是静默失败。

5. **在 `bot.py` 中对接 TRADING_BACKEND / live 开关**
   - 按 Story 6.5 的语义，确保：
     - 默认仍是 paper 模式（不触达真实资金）。
     - 只有在显式设置了对应 live 开关且 backend 选择明确时才会发送实盘订单。
   - 复用现有模式：
     - Binance 通过 `TRADING_BACKEND=binance_futures` + `BINANCE_FUTURES_LIVE=true` 激活。
     - Hyperliquid 通过 `HYPERLIQUID_LIVE_TRADING=true` 激活（推荐同时设置 `TRADING_BACKEND=hyperliquid`）。

6. **更新文档与矩阵**
   - 在 `.env.example` 注释与 README 的「Trading Backends & Live Mode Configuration」中：
     - 将新的 backend 加入枚举说明与行为矩阵（标明是否触达真实资金、需要哪些变量）。
   - 如有必要，在本文件 Epic 6 区域或相关架构文档中补充 1–2 句说明，指向：
     - `.env.example` / README 的配置段落。
     - `exchange_client.py` 与 `bot.py` 作为扩展点。

7. **为新适配器提供测试与 smoke 脚本（可选但推荐）**
   - 仿照：
     - `tests/test_exchange_client_hyperliquid.py`
     - `tests/test_exchange_client_binance_futures.py`
   - 如有实盘路径，建议新增一个 `scripts/manual_<backend>_smoke.py`，用于最小连通性验证。

---

## FR Coverage Matrix

| FR ID  | Epic                                      | Stories             |
|-------|-------------------------------------------|---------------------|
| FR-L1 | Epic 1: 支持任意 OpenAI 协议兼容 LLM 提供商 | Story 1.1（初始版） |
| FR13  | Epic 6: 统一交易所执行层 & 多交易所可插拔支持 | Story 6.1–6.5       |

---

## Summary

- 当前版本包含 2 个已规划 Epic：  
  - 平台能力 Epic 1：统一支持任意 OpenAI 协议兼容 LLM 提供商，并通过 Story 1.1 覆盖最基础的「环境变量配置与切换」能力。  
  - 交易执行 Epic 6：统一交易所执行层 & 多交易所可插拔支持，并通过 Story 6.1–6.5 规划从抽象设计到 Binance / Hyperliquid 适配与迁移的完整路径。  
