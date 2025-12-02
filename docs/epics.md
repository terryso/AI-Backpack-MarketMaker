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
- Epic 8：通过 Telegram 远程运营配置管理（允许授权用户在不重启的前提下远程调整关键运行参数，如 TRADING_BACKEND、MARKET_DATA_BACKEND、TRADEBOT_INTERVAL 和 TRADEBOT_LLM_TEMPERATURE）。
> 说明：本文件是活文档，后续可以继续追加更多 Epic 与对应 User Stories。

---

## Functional Requirements Inventory

- **FR-L1：统一的 OpenAI 协议 LLM 访问能力**  
  系统应通过一层通用的 OpenAI Chat Completions 客户端访问 LLM，只要对方提供兼容的 HTTP 接口即可；具体供应商（OpenRouter、OpenAI、自建网关等）通过配置而非代码决定。

- **FR13：统一交易所执行抽象层（Exchange Execution Layer）**  
  系统应提供一层与具体交易所无关的实盘执行抽象，使 Bot 在开仓、平仓、附带 SL/TP、错误反馈等行为上，对 Binance、Hyperliquid 以及未来新增交易所保持一致的用户体验。

- **FR-OPS1：运行时运营配置管理（Telegram 调参）**  
  系统应支持通过安全的 Telegram 命令在 Bot 运行时调整一组白名单内的关键配置项（如交易 interval、LLM temperature、主循环开关等），无需修改文件或重启进程，并具备权限校验与日志审计能力；backend 相关配置仍通过 `.env` 与重启管理。

- **FR-OPS2：可配置交易对 Universe & Telegram 管理**  
  系统应支持将可交易的合约/币对清单从代码中解耦出来，通过配置与 Telegram 命令进行管理，只影响 Paper / Live 模式的交易 Universe；新增交易对时需通过当前 `MARKET_DATA_BACKEND` 所在交易所/数据源校验其合法性，删除交易对仅阻止后续新开仓而不会强制平掉已有持仓。

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
     - 一个显式的 live 开关（例如 `MY_EXCHANGE_LIVE=true`）。
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

## FR Coverage Map

| FR ID  | Epic                                      | Stories             |
|-------|-------------------------------------------|---------------------|
| FR-L1   | Epic 1: 支持任意 OpenAI 协议兼容 LLM 提供商                    | Story 1.1（初始版）   |
| FR13    | Epic 6: 统一交易所执行层 & 多交易所可插拔支持                  | Story 6.1–6.5         |
| FR-OPS1 | Epic 8: Telegram 远程运营配置管理（Runtime Config Control）    | Story 8.1–8.4         |
| FR-OPS2 | Epic 9: 可配置交易对 Universe & Telegram 管理                  | Story 9.1–9.4         |

---

## Epic 8: Telegram 远程运营配置管理（Runtime Config Control）

### Epic 8 概述

**背景 / 问题**

- 当前更改 `TRADING_BACKEND`、`MARKET_DATA_BACKEND`、`TRADEBOT_INTERVAL`、`TRADEBOT_LLM_TEMPERATURE` 等关键运行参数，需要修改 `.env` 并重启进程，运维成本较高且不利于快速响应市场与策略变化。
- 缺乏一个安全、可审计的远程运维通道，无法在发现策略异常或市场极端波动时，快速降低风险或调整运行参数。

**目标**

- 提供一个基于 Telegram Bot 的 `/config` 命令集，让**授权管理员账号**可以在 Bot 运行时，对一组受控白名单配置项进行调整。
- 修改仅影响当前运行进程的**运行时配置**（runtime overrides），从下一轮交易循环开始生效，不写回 `.env` 文件。
- 所有配置变更均具备权限校验与日志记录能力，便于事后审计和回溯。

**范围（In Scope）**

- 在 Telegram 层新增 `/config` 命令，支持：
  - `/config list`：列出当前支持远程修改的配置项（key）及其当前生效值。
  - `/config get <KEY>`：展示指定 key 的当前值与合法取值范围/枚举说明。
  - `/config set <KEY> <VALUE>`：仅限管理员账号，修改指定 key 的运行时配置值。
- runtime overrides 层的白名单包含 backend 与调参相关的多个 key，但**当前通过 Telegram `/config` 暴露并支持修改的仅为**：
  - `TRADEBOT_INTERVAL`
  - `TRADEBOT_LLM_TEMPERATURE`
  - `TRADEBOT_LOOP_ENABLED`
- backend 相关 key（如 `TRADING_BACKEND`、`MARKET_DATA_BACKEND`）仍通过 `.env` 与进程重启来生效，避免在运行中热切换造成状态不一致。
- 在配置层增加一层「运行时覆盖」机制（runtime overrides），读取配置时优先使用 overrides，其次回退到 `.env` / 默认值，保证后续扩展更多可远程调参项的能力。

**非范围（Out of Scope）**

- 不修改 `.env` 文件内容，不提供配置版本管理或回滚功能。
- 不支持一次性批量提交多个配置变更（本 Epic 仅支持逐项 set）。
- 不在本 Epic 内引入复杂多角色权限模型，仅支持单一管理员 user_id。

**验收标准（Done Criteria）**

1. 在运行中的 Bot 中，通过 Telegram：
   - `/config list` 能返回当前支持远程修改的运行时配置项（`TRADEBOT_INTERVAL`、`TRADEBOT_LLM_TEMPERATURE`、`TRADEBOT_LOOP_ENABLED`）及其当前生效值；
   - `/config get <KEY>` 对合法/非法 key 的反馈与文档一致（非法 key 会列出受支持的 key 列表）。
2. 仅管理员 Telegram user_id 可以成功调用 `/config set <KEY> <VALUE>`，非管理员调用时收到明确的「无权限修改，只能查看」提示。
3. 对每个白名单配置项，输入非法取值时，均会返回包含合法取值范围/枚举的错误提示：
   - `TRADEBOT_INTERVAL`：仅接受 `3m`、`5m`、`15m`、`30m`、`1h`、`4h`；
   - `TRADEBOT_LLM_TEMPERATURE`：仅接受 `[0.0, 1.0]` 区间内的小数，解析为 float。
4. 在不重启进程的前提下，修改上述配置后：
   - 下一轮交易循环（或下一次使用相关配置时）实际采用新的运行时值；
   - 重启进程后配置回到 `.env` 中的原始值。
5. 每一次成功的 `/config set` 调用，都在日志中留下完整记录，包括：
   - 时间戳、Telegram user_id；
   - 配置项 key、old_value、new_value；
   - 便于后续审计和问题排查。

---

## Epic 9: 可配置交易对 Universe & Telegram 管理

### Epic 9 概述

**背景 / 问题**

- 当前可交易合约列表（如 `SYMBOLS = ["ETHUSDT", "SOLUSDT", ...]`）写死在代码中，调整交易 Universe 需要改代码和重新部署，运维开销大且不利于根据市场快速调整关注资产。
- 现有 Bot 在 Paper / Live 模式下都依赖这一硬编码列表，缺乏一个统一的、可配置且可通过 Telegram 远程调整的交易对管理机制。

**目标**

- 将 Paper / Live 模式下的交易 Universe 从代码中抽离为可配置集合，并提供 Telegram 命令对其进行查询、增删与校验。
- 新增交易对时，基于当前 `MARKET_DATA_BACKEND` 对应的市场数据/交易所接口校验 symbol 是否被支持：
  - 对 Backpack backend 使用 USDC 计价规范（例如 `xxxUSDC`）；
  - 对其它 backend 默认使用 USDT 计价规范（例如 `xxxUSDT`）。
- 删除交易对时，只阻止后续新开仓，不强制平掉已有持仓，避免引入复杂和平仓策略耦合。

**范围（In Scope）**

- 为 Paper / Live 模式引入一个「可配置交易 Universe」层，用于替代当前硬编码 `SYMBOLS`，但暂不改变回测（Backtest）的 symbol 配置方式。
- 在 Telegram Bot 中新增 `/symbols` 命令，支持：
  - `/symbols list`：查看当前 Paper / Live 交易 Universe；
  - `/symbols add <SYMBOL>`：尝试向 Universe 中添加一个新 symbol；
  - `/symbols remove <SYMBOL>`：从 Universe 中移除一个 symbol（仅影响未来的新开仓）。
- 新增 symbol 时：
  - 基于当前 `MARKET_DATA_BACKEND` 所对应的数据/交易所客户端校验 symbol 是否有效；
  - 若不支持，则返回错误并拒绝添加。
- 删除 symbol 时：
  - 若当前有持仓，则不触发强制平仓，仅确保后续不会再为该 symbol 生成新的 entry 决策或执行新开仓操作。

**非范围（Out of Scope）**

- 不改变 Backtest 的 symbol 配置方式（仍由命令行参数或脚本控制）。
- 不在本 Epic 中实现复杂的「自动调仓」或「Universe 动态优化」策略，仅支持手动增删。
- 不提供多层角色权限体系，继续沿用 Epic 8 中的管理员 user_id 权限模型。

**验收标准（Done Criteria）**

1. 在 Paper / Live 模式下，Bot 使用的交易 Universe 不再直接依赖硬编码 `SYMBOLS`，而是通过可配置集合提供，且默认值与当前行为一致。
2. 通过 Telegram：
   - `/symbols list` 能正确显示当前 Universe 中的所有 symbol；
   - `/symbols add <SYMBOL>` 在 symbol 通过 `MARKET_DATA_BACKEND` 校验时将其加入 Universe；
   - `/symbols add <SYMBOL>` 在 symbol 不被 backend 支持时返回错误并拒绝添加；
   - `/symbols remove <SYMBOL>` 将该 symbol 从 Universe 中移除，并在后续迭代中不再对其产生新开仓请求。
3. 对 Backpack backend，新增/校验 symbol 时使用 USDC 计价规范；对其它 backend 默认使用 USDT 规范（如有例外将在实现层通过映射/配置处理）。
4. 删除 symbol 后，已有持仓不被强制平仓，策略和风控仍可正常管理现有仓位，且不会再对该 symbol 创建新的 entry 信号或订单。
5. 所有通过 `/symbols add/remove` 的变更操作均写入日志，至少包含时间戳、Telegram user_id、操作类型（add/remove）、symbol、新旧 Universe 摘要。

---

### Story 9.1: 可配置交易 Universe 抽象（Paper / Live）

As a developer maintaining the trading universe,  
I want a configurable symbol universe abstraction for Paper/Live modes,  
So that tradable symbols are not hardcoded in settings.py.

**Acceptance Criteria:**

- 将当前硬编码 `SYMBOLS` 替换为一个可配置的交易 Universe 抽象（例如读取自配置文件或状态存储），对 Paper / Live 模式生效。
- 提供获取当前 Universe 列表的统一接口，供 Bot 主循环和策略层使用。
- 保持默认配置下的 Universe 与现有 `SYMBOLS` 一致，避免无意行为变化。

---

### Story 9.2: Telegram `/symbols` 命令接口（list/add/remove）

As an operator of the trading bot,  
I want a `/symbols` command with list/add/remove subcommands,  
So that I can inspect and adjust the Paper/Live trading universe via Telegram.

**Acceptance Criteria:**

- 实现 `/symbols list`：
  - 返回当前 Universe 中的所有 symbol，格式清晰，适合在聊天中阅读。
- 实现 `/symbols add <SYMBOL>`：
  - 仅管理员 user_id 可执行；
  - 调用 Story 9.3 中的校验逻辑验证 symbol 是否有效；
  - 通过校验时将 symbol 加入 Universe 并返回成功提示；
  - 未通过校验时返回错误说明（包括 backend 类型与不被支持的原因）。
- 实现 `/symbols remove <SYMBOL>`：
  - 仅管理员 user_id 可执行；
  - 从 Universe 中移除该 symbol（若不存在则返回提示但不报错）；
  - 文案上明确说明「仅阻止后续新开仓，不会强制平掉当前持仓」。

---

### Story 9.3: 基于 `MARKET_DATA_BACKEND` 的 symbol 校验

As a developer integrating exchange/data backends,  
I want symbol validation to respect the current `MARKET_DATA_BACKEND`,  
So that a symbol is only added if it is supported by the active market data source.

**Acceptance Criteria:**

- 基于当前 `MARKET_DATA_BACKEND`，调用对应的交易所或数据客户端查询是否支持某个 symbol：
  - 对 Backpack backend，按 USDC 计价规范处理（如 `BTCUSDC`）；
  - 对其它 backend，按 USDT 计价规范处理（如 `BTCUSDT`），如需额外映射在实现时补充。
- 校验失败时，返回包含 backend 类型和失败原因的错误信息，用于 Telegram 反馈。
- 提供最小测试覆盖，验证在至少两种 backend 下的校验行为（例如 Backpack + Binance）。

---

### Story 9.4: 行为约定、日志与文档更新

As the owner of the trading system,  
I want clear behavioral contracts, logging, and docs for symbol management,  
So that changes to the trading universe are predictable and auditable.

**Acceptance Criteria:**

- 明确并在代码/文档中说明：
  - 通过 `/symbols remove` 删除 symbol 仅阻止新开仓，对已有持仓不做强制平仓处理；
  - Backtest 仍使用独立的 symbol 配置通道，与 Paper / Live 的 Universe 解耦。
- 为 `/symbols add/remove` 操作增加日志记录：
  - 至少包含时间戳、Telegram user_id、操作类型（add/remove）、symbol、新旧 Universe 摘要；
  - 日志格式与现有 logging 体系兼容。
- 在 README 或相关文档中增加一节「可配置交易 Universe & Telegram 管理」，概述：
  - `/symbols` 命令用法；
  - 与 `MARKET_DATA_BACKEND` 的关系；
  - Backpack USDC vs 其它 backend USDT 的命名约定；
  - 删除 symbol 时对持仓和风险的影响说明。

---

### Story 8.1: 运行时配置覆盖层（Runtime Overrides）

As a developer maintaining the configuration system,  
I want a runtime overrides layer on top of env-based settings,  
So that Telegram-triggered config changes take effect without rewriting `.env` or restarting the process.

**Acceptance Criteria:**

- 定义一个集中管理的 runtime overrides 容器（例如基于 dict 或配置对象包装），支持按 key 设置/读取当前运行时值。
- 所有受 Epic 8 影响的配置项（4 个白名单 key）在读取时均遵循统一优先级：runtime override > `.env` / 默认值。
- 对不存在的 key 或未设置 override 的 key，有清晰的回退行为和类型安全保证（不会抛出意外异常）。
- 为 overrides 层提供最小单元测试或集成测试，验证读写优先级与回退逻辑。

---

### Story 8.2: Telegram `/config` 命令接口

As an operator of the trading bot,  
I want a `/config` command with list/get/set subcommands,  
So that I can inspect and adjust key runtime parameters via Telegram.

**Acceptance Criteria:**

- 在 Telegram Bot 中实现 `/config list`：
  - 返回当前支持远程修改的运行时配置项（`TRADEBOT_INTERVAL`、`TRADEBOT_LLM_TEMPERATURE`、`TRADEBOT_LOOP_ENABLED`）及其当前生效值。
- 在 Telegram Bot 中实现 `/config get <KEY>`：
  - 对合法 key 返回当前值和合法取值范围/枚举说明；
  - 对非法 key 返回错误信息，并列出受支持的 key 列表。
- 在 Telegram Bot 中实现 `/config set <KEY> <VALUE>`：
  - 收到合法 key + 合法 value 时，调用 runtime overrides 层更新对应配置项；
  - 返回包含 old_value/new_value 的成功提示；
  - 对非法 value 返回明确的错误和合法值提示。

---

### Story 8.3: 权限控制与审计日志

As the owner of the trading system,  
I want strict admin-only permissions and audit logs for config changes,  
So that sensitive runtime adjustments are controlled and traceable.

**Acceptance Criteria:**

- 在配置中支持配置一个管理员 Telegram user_id（或等价机制）。
- `/config set` 仅在请求方 user_id 匹配管理员配置时才会执行：
  - 非管理员调用时返回「无权限修改，只能查看」提示，不改动任何配置。
- 每次成功的 `/config set` 调用都会写入日志，至少包括：
  - 时间戳、Telegram user_id、key、old_value、new_value；
  - 日志级别和格式与现有 logging 体系兼容。

---

### Story 8.4: 端到端验证与文档更新

As a maintainer of the bot,  
I want end-to-end tests and updated docs for the runtime config feature,  
So that the behavior is reliable and clearly communicated.

**Acceptance Criteria:**

- 至少完成一次端到端验证：
  - 在本地或测试环境中运行 Bot；
  - 通过 Telegram 修改上述 4 个配置项中的至少 2 个；
  - 观察下一轮交易循环中配置已按预期生效，且重启后恢复 `.env` 默认值。
- 在 README 或配置说明文档中增加一小节，简要说明：
  - `/config` 命令的用法（list/get/set）；
  - 受支持的配置项及其取值范围；
  - 权限与风险提示（仅管理员可修改，不会自动写回 `.env`）。

---

## Summary

- 当前版本包含 4 个已规划 Epic：  
- 平台能力 Epic 1：统一支持任意 OpenAI 协议兼容 LLM 提供商，并通过 Story 1.1 覆盖最基础的「环境变量配置与切换」能力。  
- 交易执行 Epic 6：统一交易所执行层 & 多交易所可插拔支持，并通过 Story 6.1–6.5 规划从抽象设计到 Binance / Hyperliquid 适配与迁移的完整路径。  
- 运营配置 Epic 8：通过 Telegram 远程运营配置管理（Runtime Config Control），为授权管理员提供运行时参数调节能力（交易后端、行情后端、interval、LLM temperature），降低运维摩擦。  
- 安全与风控 Epic 7：风控系统增强（Emergency Controls），通过 Epic 7.1–7.4 规划从风控基础设施、Kill-Switch、每日亏损限制到 Telegram 命令集成的完整路径，并与独立风控 PRD 对齐。  

## Epic 7: 风控系统增强（Emergency Controls）

### Epic 7 概述

**背景 / 问题**

- 当前 Bot 已有基础风险控制与资金管理（单笔风险、必带止损等），但缺乏**系统级应急控制能力**：
  - 无法在发现策略失效或市场异常时，一键「拉闸」停止新开仓；
  - 无法基于每日亏损动态收紧风险；
  - 缺少通过 Telegram 命令远程控制风控状态的能力。
- README / 主 PRD 已在路线图中提到 Kill-Switch 等能力，但尚未在 Epic 层正式建模并与 Story 对齐。

**目标**

- 为 DeepSeek Paper Trading Bot 建立一条「应急控制（Emergency Controls）」能力线，涵盖：
  - 统一的风控状态模型与持久化（RiskControlState）；
  - Kill-Switch（紧急停止）；
  - 每日亏损限制（Daily Loss Limit）；
  - 通过 Telegram 的远程控制命令。
- 在 MVP 阶段，至少保证：
  - 风控状态模型 + 主循环集成（Epic 7.1 完整交付）；
  - Kill-Switch 可通过配置/内部逻辑激活并**可靠阻止新开仓**（Story 7-2-1）。

---

### Epic 7.1: 风控状态管理基础设施（MVP）

> 对应 Tech Spec：`docs/sprint-artifacts/tech-spec-epic-7-1.md`  
> 对应 PRD：`docs/prd-risk-control-enhancement.md` 中「风控状态管理」部分

**范围（In Scope）**

- 定义 `RiskControlState` 数据结构，统一承载 Kill-Switch 与每日亏损等风控状态。
- 将风控状态持久化到 `portfolio_state.json.risk_control`，使用原子写入并保持向后兼容。
- 在 `bot.py` 主循环中集成风控状态加载、检查与保存，为后续 Epic 7.2 / 7.3 / 7.4 预留入口。

**Stories**

- 7-1-1 定义 RiskControlState 数据结构（done）
- 7-1-2 添加风控相关环境变量（done）
- 7-1-3 实现风控状态持久化（done）
- 7-1-4 集成风控状态到主循环（done）

> 本 Epic 已完整交付，为后续 Kill-Switch / 日亏 / Telegram 功能提供技术基座。详见 Epic Retro：  
> `docs/sprint-artifacts/epic-7-1-retro-risk-control.md`

---

### Epic 7.2: Kill-Switch 核心功能（部分纳入 MVP）

> 对应 PRD：`docs/prd-risk-control-enhancement.md` 中「Kill-Switch 功能」部分

**范围（In Scope）**

- 基于 `RiskControlState` 与风控配置，实现 Kill-Switch 的：
  - 激活/判定逻辑；
  - 对 LLM 决策的拦截规则（阻止 entry，允许 close + SL/TP）。
- 支持通过环境变量 `KILL_SWITCH`、后续的 Telegram 命令等方式控制 Kill-Switch 状态。

**MVP 子集**

- 7-2-1 实现 Kill-Switch 激活逻辑（ready-for-dev）  
  - 定义 `KILL_SWITCH` 与持久化状态之间的优先级规则（env 优先）；  
  - 在 `_run_iteration()` 开始阶段通过 `check_risk_limits()` 判定是否应阻止本轮 entry；  
  - 在 Kill-Switch 激活时拒绝所有 `signal="entry"`，但保留 `signal="close"` 与现有 SL/TP 检查。

**Post-MVP（规划中）**

- 7-2-2 实现 Kill-Switch 解除逻辑  
- 7-2-3 实现信号过滤逻辑（例如只允许风险减轻方向的操作）  
- 7-2-4 确保 SL/TP 在 Kill-Switch 期间正常工作（迭代细化现有逻辑与日志）  
- 7-2-5 实现 Kill-Switch 状态变更通知（与 Telegram / 仪表盘对齐）

---

### Epic 7.3: 每日亏损限制功能（Post-MVP）

> 对应 PRD：`docs/prd-risk-control-enhancement.md` 中「每日亏损限制」部分

**范围（In Scope）**

- 基于 `RiskControlState.daily_start_equity` / `daily_start_date` / `daily_loss_pct`：
  - 记录每日起始权益并在 UTC 跨日自动重置；
  - 在每次迭代计算当日亏损百分比，与 `DAILY_LOSS_LIMIT_PCT` 对比；
  - 当达到阈值时自动激活 Kill-Switch。

**Stories（规划中）**

- 7-3-1 实现每日起始权益记录  
- 7-3-2 实现每日亏损百分比计算  
- 7-3-3 实现每日亏损阈值触发（联动 Kill-Switch）  
- 7-3-4 实现每日亏损限制通知

> 全部视为 **post-MVP**，在 Kill-Switch 核心功能稳定后分批进入。

---

### Epic 7.4: Telegram 命令集成（Post-MVP）

> 对应 PRD：`docs/prd-risk-control-enhancement.md` 中「Telegram 命令集成」部分

**范围（In Scope）**

- 基于已持久化的 `RiskControlState` 与 Kill-Switch / 日亏逻辑：
  - 通过 Telegram 命令 `/kill`、`/resume`、`/status`、`/reset_daily` 等远程控制风控状态；
  - 对敏感操作（特别是 `/resume`）进行二次确认；
  - 确保只有授权的 `TELEGRAM_CHAT_ID` 能触发命令。

**Stories（规划中）**

- 7-4-1 实现 Telegram 命令接收机制  
- 7-4-2 实现 kill 和 resume 命令（含二次确认）  
- 7-4-3 实现 status 命令（展示当前风控状态与关键字段）  
- 7-4-4 实现 reset-daily 命令（重置每日亏损基准）  
- 7-4-5 实现 help 命令和安全校验

> 整个 Epic 7.4 为 **post-MVP**，在 Kill-Switch + 日亏逻辑稳定后作为 UX/操控能力增强。
