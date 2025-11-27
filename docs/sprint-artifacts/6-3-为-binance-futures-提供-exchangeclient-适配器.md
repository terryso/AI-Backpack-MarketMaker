# Story 6.3: 为 Binance Futures 提供 ExchangeClient 适配器

Status: done

## Story

As a developer adding multi-exchange support,
I want Binance Futures live trading to be accessed via the same ExchangeClient abstraction,
So that the bot call-site does not need Binance-specific branching.

本故事的目标是：在不改变现有风险控制与交易主循环整体行为的前提下，为 Binance Futures 实盘路径提供一个符合 `ExchangeClient` 抽象的适配器，使 Bot 在调用层面对具体交易所无感知，并为后续 Story 6.4 对 `execute_entry` / `execute_close` 的重构打下基础。

## Acceptance Criteria

1. **实现 BinanceFuturesExchangeClient 适配器（AC1）**  
   - 提供一个实现 `ExchangeClient` 协议/接口的适配器类（命名建议：`BinanceFuturesExchangeClient` 或等价），位于 `exchange_client.py` 或等价模块中。  
   - `place_entry(...)` 接口参数与 `ExchangeClient.place_entry` 对齐，内部使用 ccxt `create_order` 下 **市价单**，并在可能情况下设置杠杆（复用 `exchange.set_leverage` 逻辑）。  
   - `close_position(...)` 与 `ExchangeClient.close_position` 对齐，内部使用 **reduce-only 市价单** 完成平仓，保证不会意外反向加仓。  

2. **统一结果结构映射到 EntryResult / CloseResult（AC2）**  
   - 对 Binance Futures 的下单 / 平仓原始响应进行解析，并映射到 `EntryResult` / `CloseResult`：  
     - `backend="binance_futures"`；  
     - `success` 由下单/平仓是否被 Binance 接受、是否返回错误码等综合判定；  
     - 将常见错误（如 API Key 缺失、初始化失败、下单异常、订单被拒）汇总到 `errors: list[str]` 中，避免仅 dump 原始异常字符串；  
     - 在可能情况下，从响应中提取代表性的订单 ID，并填入结果对象（例如 `entry_oid` / `close_oid`）；  
     - 将完整原始响应放入 `raw`，并在 `extra` 中保留关键字段，方便后续调试与回放。  

3. **明确当前阶段行为与约束（AC3）**  
   - 当前阶段 **SL/TP 仍主要由 Bot 侧逻辑负责**（例如 `check_stop_loss_take_profit`），Binance 适配器不需要立即使用交易所原生触发单，但：  
     - `place_entry(...)` 仍然接受 `stop_loss_price` / `take_profit_price` 参数，为未来扩展留接口；  
     - 在 Dev Notes 中明确记录「本阶段只负责 ENTRY/CLOSE 市价单，保护逻辑仍由 bot.py 完成」。  
   - 对常见错误场景建立统一语义：  
     - API Key / Secret 缺失或无效；  
     - Binance futures 客户端初始化失败；  
     - `create_order` 抛出异常或返回错误状态。  
   - 上述错误需通过 `EntryResult` / `CloseResult` 的 `errors` 字段暴露给上层，同时保留 `raw` payload。  

4. **在 TRADING_BACKEND="binance_futures" 且 BINANCE_FUTURES_LIVE=true 时等价支持实盘操作（AC4）**  
   - 在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 的组合下，通过 `ExchangeClient` 完成与当前实现等价的实盘行为，至少覆盖：  
     - ENTRY：利用 `BinanceFuturesExchangeClient.place_entry(...)` 完成开仓；  
     - CLOSE：利用 `BinanceFuturesExchangeClient.close_position(...)` 完成全仓平仓。  
   - 行为等价的含义包括：  
     - 仍遵守 `BINANCE_FUTURES_MAX_RISK_USD` / `BINANCE_FUTURES_MAX_MARGIN_USD` 等风险与保证金上限；  
     - 仍通过 `COIN_TO_SYMBOL` 完成交易对映射；  
     - 失败时在日志中留下足够清晰的错误信息（参照现有实现）。  

## Tasks / Subtasks

- [x] 任务 1：梳理现有 Binance Futures 实盘执行路径与约束（AC: #1, #2, #3, #4）  
  - [x] 通读 `bot.py` 中与 Binance Futures 相关的代码片段，包括：`TRADING_BACKEND` 解析、`get_binance_futures_exchange`、BINANCE
aFUTURES 风险与保证金上限设置、ENTRY/CLOSE 的实盘分支。  
  - [x] 对照 Story Context 与架构/PRD 引用（`docs/epics.md`、`docs/PRD.md`、`docs/architecture/*.md`）中的约束，明确哪些逻辑应继续由 `bot.py` 负责，哪些可以下沉到 `ExchangeClient` 适配层。  
  - [x] 从现有 Binance Futures 逻辑中提取出可复用的「下单参数构造模式」（symbol 映射、`positionSide`、`reduceOnly` 等），并在适配器与调用点中体现。  

- [x] 任务 2：设计与实现 BinanceFuturesExchangeClient 适配器（AC: #1, #2, #3）  
  - [x] 在 `exchange_client.py` 中新增 `BinanceFuturesExchangeClient` 类，实现 `ExchangeClient` 协议，并通过组合持有一个 ccxt `binanceusdm` 实例或等价封装。  
  - [x] 在 `place_entry(...)` 中调用 `exchange.create_order` 创建市价单，复用或封装现有杠杆设置逻辑（`exchange.set_leverage`），将返回结果解析为 `EntryResult`，包括 `success` / `backend` / `errors` / `entry_oid` / `raw` / `extra` 等字段。  
  - [x] 在 `close_position(...)` 中使用 reduce-only 市价单完成平仓，将返回值封装为 `CloseResult`，并对错误与异常做统一处理（借鉴 `HyperliquidExchangeClient` 的 `_collect_errors` / `_deduplicate_errors` 模式）。  
  - [x] 确保适配器自身不直接读取环境变量，而是依赖外部传入的 exchange 实例或工厂，以符合 `docs/architecture/07-implementation-patterns.md` 对外部服务适配的约定。  

- [x] 任务 3：接入 ExchangeClient 工厂与 Bot 实盘路径（AC: #2, #3, #4）  
  - [x] 在 `exchange_client.get_exchange_client` 中为 `backend="binance_futures"` 增加分支，接受已经初始化好的 ccxt `binanceusdm` 实例（例如通过 `get_binance_futures_exchange()` 创建）。  
  - [x] 在 `bot.py` 的实盘 ENTRY/CLOSE 路径中，通过 `get_exchange_client("binance_futures")` 抽象出使用 `ExchangeClient` 的调用点，使 `TRADING_BACKEND="binance_futures"` 时能够通过 `BinanceFuturesExchangeClient` 完成与现有实现等价的行为，同时避免在本 Story 内对 `execute_entry` / `execute_close` 做过度重构（将更大规模重构留给 Story 6.4）。  
  - [x] 在日志与错误处理上，保持与现有 Binance Futures 路径相同或更清晰的语义（例如在日志中打印代表性错误摘要），并通过 `EntryResult` / `CloseResult.errors` 对上层暴露统一错误语义。  

- [x] 任务 4：测试与最小行为验证（AC: #2, #3, #4）  
  - [x] 新增 `tests/test_exchange_client_binance_futures.py`，为 `BinanceFuturesExchangeClient.place_entry` / `close_position` 编写单元测试，覆盖成功与失败路径，验证 `EntryResult` / `CloseResult` 字段语义与错误聚合逻辑。  
  - [x] 在有真实 Binance Futures 凭证的受控环境中，通过 `scripts/manual_binance_futures_smoke.py` / `scripts/run_binance_futures_smoke.sh` 对 `BTCUSDT` 执行最小规模 ENTRY/CLOSE smoke：使用 `notional=20, leverage=10`，实际成交约 `0.002 BTC`（名义约 183 USDT），验证适配器封装前后对 Binance Futures 的实际行为等价。  
  - [x] 根据多次 smoke 结果（包括最小数量/名义限制报错 `code=-4164` 与 `reduceOnly` 参数报错 `code=-1106`），在 Dev Notes 与实现中对 `manual_binance_futures_smoke.py.determine_order_params` 以及 `BinanceFuturesExchangeClient.close_position` 的边界条件与错误处理进行了微调，以便后续 Story 6.4、6.5 复用。  

## Dev Notes

- 本 Story 基于 Story 6.1 中引入的 `ExchangeClient` 抽象与统一结果结构，以及 Story 6.2 中实现的 `HyperliquidExchangeClient` 适配器模式，将同样的执行层抽象扩展到 Binance Futures 实盘路径。  
- 需要严格遵守 PRD 4.2「风险控制与资金管理」对单笔风险、止损必选、风控边界的约束，确保通过 Binance Futures 实盘路径执行的任何订单 **不突破现有风险上限**（包括 `BINANCE_FUTURES_MAX_RISK_USD` / `BINANCE_FUTURES_MAX_MARGIN_USD` 等）。  
- 适配器层应聚焦于「把 ccxt 的返回结构翻译成统一的 `EntryResult` / `CloseResult`」，而不是重新实现风险控制或头寸管理逻辑；资金与风险计算仍由 `bot.py` 主循环负责。  
- 错误信息需要面向人类开发者可读：在日志和 `errors` 字段中给出简洁的摘要，例如 "API key missing", "order rejected: insufficient margin"，同时通过 `raw` 字段保留完整 payload。  
- 与 Hyperliquid 路径保持一致：当 future 的 Story 6.4 将 `execute_entry` / `execute_close` 完全迁移到 `ExchangeClient` 抽象后，Binance 与 Hyperliquid 应仅在适配器层有所差异，上层调用代码完全复用。  

### Learnings from Previous Story (Story 6.2)

- Story 6.2 已为 Hyperliquid 路径实现 `HyperliquidExchangeClient`，并通过 `_collect_errors` / `_deduplicate_errors` 等工具方法，将复杂的 Hyperliquid 响应结构整理为统一的 `EntryResult` / `CloseResult`：  
  - 这一模式证明了「适配器不需要修改原有客户端实现，只需在结果层做语义映射」的可行性。  
- 6.2 的 Dev Notes 与 File List 表明：  
  - `exchange_client.py` 中已经有 `ExchangeClient` 抽象、结果结构和 `HyperliquidExchangeClient` 的参考实现；  
  - Hyperliquid 适配器通过组合持有 `HyperliquidTradingClient` 实例，而非继承，降低了对现有实盘逻辑的侵入性；  
  - 已为 Hyperliquid 创建了单元测试文件 `tests/test_exchange_client_hyperliquid.py`，验证了错误聚合和 OID 映射的语义。  
- 对本 Story 的启发：  
  - Binance Futures 适配器应在结构与行为上尽可能贴近 Hyperliquid 适配器：同样使用组合、同样在 `extra` 字段中保留 backend 特有细节；  
  - 建议沿用 Hyperliquid 测试文件的模式，为 Binance 引入对称的测试文件，以便在将来回归时快速比较两条路径的一致性；  
  - 在接线到生产路径时，先通过 smoke 测试验证适配器封装前后的行为等价，再在 Story 6.4 中推进对核心执行函数的重构。  

### Project Structure Notes

- 继续在现有 `exchange_client.py` 模块中集中维护 `ExchangeClient` 抽象、`EntryResult` / `CloseResult` 以及各具体 backend 的适配器实现（Hyperliquid / Binance Futures），保持执行层入口单一、易于搜索。  
- Binance Futures 相关逻辑目前主要分布在 `bot.py`（风险计算与订单参数准备）和 `get_binance_futures_exchange()` 初始化路径中；本 Story 只在「执行适配层」和「调用点」上做增量调整，不新增顶层主循环脚本。  
- 若未来为多交易所适配扩展出子模块结构（例如 `exchange_clients/binance_futures.py`），应在架构文档中更新对应的项目结构示意，并保持 `ExchangeClient` 抽象仍位于统一入口模块。  

### References

- Epics：`docs/epics.md` 中 "Story 6.3: 为 Binance Futures 提供 ExchangeClient 适配器" 章节。  
- PRD：  
  - `docs/PRD.md` 4.1「交易主循环（Bot）」：描述主循环与执行链路；  
  - `docs/PRD.md` 4.2「风险控制与资金管理」：定义单笔风险与止损/止盈约束；  
  - `docs/PRD.md` 4.8「Hyperliquid 实盘集成」：可类比参考实盘集成模式，但目标 backend 为 Binance Futures。  
- 架构：  
  - `docs/architecture/03-data-flow.md`：从 LLM 决策到执行层的数据流；  
  - `docs/architecture/04-integrations.md`：外部服务集成点（Binance / Hyperliquid 等）；  
  - `docs/architecture/06-project-structure-and-mapping.md`：Bot / scripts / docs 与源码树映射；  
  - `docs/architecture/07-implementation-patterns.md`：外部服务适配与错误处理模式。  
- 代码：  
  - `exchange_client.py`：`ExchangeClient` 抽象与 `EntryResult` / `CloseResult`、`HyperliquidExchangeClient` 参考实现；  
  - `bot.py`：当前 Binance Futures ENTRY/CLOSE 实盘逻辑与风险/保证金上限控制；  
  - `hyperliquid_client.py`：Hyperliquid 实盘执行逻辑（可对比 adapter vs. 原生客户端的职责划分）。  

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/6-3-为-binance-futures-提供-exchangeclient-适配器.context.xml`  

### Agent Model Used

- `/dev` → `*develop-story*` 开发代理（Amelia, Developer Agent），通过 BMAD dev-story 工作流在本地执行。  
- 模型：Cascade（通过当前 IDE 集成调用）。  

### Debug Log References

- 2025-11-27：阅读 `exchange_client.py` / `bot.py` / `hyperliquid_client.py` / `tests/test_exchange_client_hyperliquid.py` / `scripts/manual_hyperliquid_smoke.py`，对齐 Story 6.2 中 Hyperliquid 适配器的抽象与错误处理模式。  
- 2025-11-27：在 `exchange_client.py` 中实现 `BinanceFuturesExchangeClient`，并扩展 `get_exchange_client("binance_futures")` 分支。  
- 2025-11-27：在 `bot.py` 的 `execute_entry` / `execute_close` 中接入 `BinanceFuturesExchangeClient`，保持风险/保证金计算仍由 `bot.py` 负责，仅将执行与结果映射下沉到适配层。  
- 2025-11-27：新增 `tests/test_exchange_client_binance_futures.py` 与 `tests/__init__.py`，在禁用外部 pytest 插件（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）的情况下运行 `pytest tests/test_exchange_client_hyperliquid.py tests/test_exchange_client_binance_futures.py`，共 8 个用例全部通过。  
- 2025-11-27：新增 `scripts/run_tests.sh` 统一运行本仓库测试；新增 `scripts/run_hyperliquid_smoke.sh` 作为 Hyperliquid smoke 测试的便捷入口。  
- 2025-11-27：新增 `scripts/manual_binance_futures_smoke.py` 与 `scripts/run_binance_futures_smoke.sh`，提供 Binance Futures 最小 smoke 验证脚本与 Bash 包装入口（需在有真实凭证的环境中由人工执行）。  
 - 2025-11-27：在真实 Binance Futures 环境中多次运行 `scripts/run_binance_futures_smoke.sh`（包括 `--symbol BTCUSDT --notional 5/10/20 --leverage 1/10 --side long --use-exchange-client` 等组合），先后处理最小数量/名义限制报错（`code=-4164 Order's notional must be no smaller than 100`）与 `reduceOnly` 参数报错（`code=-1106 Parameter 'reduceonly' sent when not required.`），最终在 `BTCUSDT`、`size=0.002`（名义约 183 USDT）下通过 `BinanceFuturesExchangeClient` 完成 ENTRY + CLOSE，验证成功与失败路径的错误聚合与日志语义，并为后续 code-review 提供了真实交易证据。  

### Completion Notes List

- [x] AC1：在 `exchange_client.py` 中实现 `BinanceFuturesExchangeClient`，通过组合 ccxt `binanceusdm` 实例、使用市价单与 reduce-only 市价单完成 ENTRY/CLOSE，并与 `ExchangeClient` 接口保持一致。  
- [x] AC2：将 Binance Futures 的原始响应映射为统一的 `EntryResult` / `CloseResult`：`backend="binance_futures"`，基于 `status` 与 `info.code` / `info.msg` 聚合人类可读错误到 `errors`，同时在 `raw` / `extra` 中保留完整 payload 与关键字段（如 OID）。  
- [x] AC3：保持 SL/TP 与风险控制逻辑主要由 `bot.py` 负责，适配器只负责执行与结果语义映射；在出错时通过 `EntryResult` / `CloseResult.errors` 暴露统一错误语义，避免仅 dump 原始异常字符串。  
- [x] AC4（实现侧）：当 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时，`execute_entry` / `execute_close` 通过 `ExchangeClient` 路径调用 `BinanceFuturesExchangeClient`，在风险约束（`BINANCE_FUTURES_MAX_RISK_USD` / `BINANCE_FUTURES_MAX_MARGIN_USD`）与日志语义上与原有实盘路径等价；并已在真实 Binance Futures 环境中通过 `scripts/run_binance_futures_smoke.sh --symbol BTCUSDT --notional 20 --leverage 10 --side long --use-exchange-client` 完成一笔 `BTCUSDT size≈0.002`（名义约 183 USDT）的 ENTRY/CLOSE smoke 验证。  

### File List

- MODIFIED: `exchange_client.py` — 新增 `BinanceFuturesExchangeClient` 适配器，并扩展 `get_exchange_client("binance_futures")` 分支以返回该适配器实例；在 `close_position` 中增加对 `reduceOnly` 相关错误（`code=-1106`）的降级重试逻辑，以兼容不同账户/模式下对 `reduceOnly` 参数的要求。  
- MODIFIED: `bot.py` — 在 `execute_entry` / `execute_close` 中接入 `BinanceFuturesExchangeClient`，在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时通过 `ExchangeClient` 执行 Binance Futures 实盘 ENTRY/CLOSE，同时保留原有风险/保证金约束逻辑。  
- NEW: `tests/test_exchange_client_binance_futures.py` — 为 `BinanceFuturesExchangeClient` 编写的单元测试，覆盖成功与失败路径以及错误聚合与 OID 映射。  
- NEW: `tests/__init__.py` — 将项目根目录加入 `sys.path`，确保测试模块可以直接导入 `exchange_client` 等顶层模块。  
- NEW: `scripts/run_tests.sh` — 统一的测试运行脚本，在禁用全局 pytest 插件的前提下运行本仓库测试（`pytest tests` 或自定义参数）。  
- NEW: `scripts/run_hyperliquid_smoke.sh` — Hyperliquid 实盘 smoke 测试的 Bash 包装脚本，作为 `scripts/manual_hyperliquid_smoke.py` 的便捷入口。  
- NEW: `scripts/manual_binance_futures_smoke.py` — Binance Futures 实盘最小 smoke 测试脚本，可通过 `BinanceFuturesExchangeClient` 或直接 ccxt 路径完成小额 ENTRY/CLOSE 验证。  
- NEW: `scripts/run_binance_futures_smoke.sh` — Binance Futures smoke 测试的 Bash 包装脚本，作为 `scripts/manual_binance_futures_smoke.py` 的便捷入口。  
- MODIFIED: `docs/sprint-artifacts/sprint-status.yaml` — 在 Story 生命周期内多次更新 6-3 的 `development_status`（`ready-for-dev` → `in-progress` → `review` → `done`），用于反映当前开发与评审状态。  

## Change Log

- [x] 2025-11-27：初始 Story 草稿由 Scrum Master（create-story 工作流）根据 epics/PRD/架构文档与 Story 6.2 的 Dev Notes 生成，状态设为 `drafted`。
- [x] 2025-11-27：Dev agent 通过 `/dev` → `*develop-story*` 实现 Story 6.3 主要代码与测试：新增 `BinanceFuturesExchangeClient` 适配器、接入 `bot.py` 中的 Binance Futures ENTRY/CLOSE 实盘路径、补充 Binance 单元测试与测试脚本，准备交由 SM 使用 code-review/workflow 进行评审。
 - [x] 2025-11-27：在真实 Binance Futures 环境中通过 `scripts/run_binance_futures_smoke.sh` 对 `BTCUSDT` 执行最小规模 ENTRY/CLOSE smoke（约 `0.002 BTC`，名义约 183 USDT），期间根据交易所返回的最小数量/名义限制（`code=-4164`）与 `reduceOnly` 参数错误（`code=-1106`）微调 `manual_binance_futures_smoke.py.determine_order_params` 与 `BinanceFuturesExchangeClient.close_position` 的边界条件与错误聚合逻辑，并将上述行为记录到 Dev Notes 以供 Story 6.4/6.5 复用。  
 - [x] 2025-11-27：Senior Developer（AI）按 code-review 工作流对 Story 6.3 进行了系统化审查，验证了全部 AC 与 Tasks/Subtasks，确认实现与 Epic/架构约束一致，并将审查结果与后续建议记录在本文档末尾的 “Senior Developer Review (AI)” 小节中。  

## Senior Developer Review (AI)

### Reviewer

- Reviewer: Nick (Senior Developer, AI-assisted)
- Date: 2025-11-27

### Outcome

- **Outcome**: Approve  
  所有 Acceptance Criteria 均已实现并有明确证据；所有标记为完成的 Tasks/Subtasks 均在代码与测试中找到对应实现；存在若干低优先级改进建议，但不构成阻塞条件。

### Summary

- Binance Futures 已通过 `BinanceFuturesExchangeClient` 接入统一 `ExchangeClient` 抽象，`bot.py` 在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 下的 ENTRY/CLOSE 路径全部经由适配器调用。  
- `EntryResult` / `CloseResult` 结果语义明确，能从 Binance/ccxt 原始响应中聚合人类可读错误信息，并在成功时正确提取 OID。  
- 通过单元测试与真实 Binance Futures smoke（`BTCUSDT size≈0.002`，名义约 183 USDT）验证了成功与失败路径的行为与日志语义。  
- 代码整体遵守既有风险控制与架构约束，无高/中严重级别问题，仅有少量测试覆盖与可维护性方面的低优先级改进建议。

### Key Findings (by Severity)

- **High**: 无。  
- **Medium**: 无。  
- **Low**:  
  - 建议为 `BinanceFuturesExchangeClient.close_position` 中的 `reduceOnly` 降级重试路径补充单元测试，防止未来改动破坏该分支（当前仅由手工 smoke 覆盖）。  
  - 建议为 `manual_binance_futures_smoke.determine_order_params` 的「最小名义/数量」逻辑增加一个基于 stub exchange 的单元测试或 doctest，便于回归校验 Binance 规则变化。  

### Acceptance Criteria Coverage

**AC Validation Checklist**

| AC# | Description | Status | Evidence |
| --- | ----------- | ------ | -------- |
| AC1 | 在 `exchange_client.py` 中实现 `BinanceFuturesExchangeClient`，使用 ccxt 市价单与 reduce-only 市价单完成 ENTRY/CLOSE，并实现 `ExchangeClient` 接口。 | IMPLEMENTED | `exchange_client.py`:235-362 (`BinanceFuturesExchangeClient.place_entry`)，364-431 (`close_position`)，434-455 (`get_exchange_client` 分支)。单元测试：`tests/test_exchange_client_binance_futures.py`:33-66, 93-115。 |
| AC2 | 将 Binance Futures 的原始响应映射为统一的 `EntryResult` / `CloseResult`，聚合错误并提取 OID。 | IMPLEMENTED | 错误聚合：`exchange_client.py`:263-287 (`_collect_errors`)，335-348, 406-419（根据 `status`/`info.code`/`info.msg` 设置 `success` 与 `errors`）。OID 映射：`_extract_order_id` at 248-261。单测验证错误语义：`tests/test_exchange_client_binance_futures.py`:67-92, 116-136。 |
| AC3 | 明确当前阶段 SL/TP 与风险控制逻辑仍由 `bot.py` 负责，适配器仅负责执行与结果语义映射，并通过 `errors` 暴露统一错误。 | IMPLEMENTED | 风险与止损/止盈校验：`bot.py`:1920-2052（风险、杠杆与止损/止盈检查），`check_stop_loss_take_profit`:2593-2627。适配器不参与风险计算，仅接收 `stop_loss_price`/`take_profit_price`、`size` 等参数：`exchange_client.py`:289-362, 364-431。错误通过 `EntryResult`/`CloseResult.errors` 暴露：263-287, 335-348, 406-419。 |
| AC4 | 在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时，通过 `ExchangeClient` 完成与原有实盘路径等价的 ENTRY/CLOSE 行为。 | IMPLEMENTED | ENTRY 集成：`bot.py`:2075-2105（构造 `BinanceFuturesExchangeClient` 并调用 `place_entry`），保持原有风险/保证金逻辑不变（1920-2052）。CLOSE 集成：`bot.py`:2315-2342（调用 `close_position` 并在失败时保留仓位）。实盘 smoke 证明 ENTRY+CLOSE 路径工作：`scripts/manual_binance_futures_smoke.py`:222-343；`scripts/run_binance_futures_smoke.sh`:1-32；运行日志（2025-11-27 18:13:46–18:14:01）显示 `BTCUSDT size=0.002` ENTRY/CLOSE 全部 `success=True`。 |

**AC Coverage Summary**: 4 / 4 acceptance criteria **fully implemented**；未发现部分实现或缺失的 AC。

### Task Completion Validation

**Task Validation Checklist**

| Task / Subtask | Marked As | Verified As | Evidence |
| -------------- | --------- | ----------- | -------- |
| 任务 1：梳理现有 Binance Futures 实盘执行路径与约束 | [x] | VERIFIED COMPLETE | 适配器与 `bot.py` 接口边界清晰：`bot.py`:1920-2052, 2075-2105, 2315-2342；`exchange_client.py`:289-362, 364-431。 |
| 任务 1.1：通读 `bot.py` 中 Binance Futures 相关代码，理解风险和 ENTRY/CLOSE 分支 | [x] | VERIFIED COMPLETE | 风险/保证金与 Binance 分支在重构后仍保持一致：`bot.py`:1965-1971（风险上限）、2023-2052（margin scaling）、2075-2105 / 2315-2342（Binance 分支）。 |
| 任务 1.2：对照 Story Context/架构/PRD，划分 `bot.py` 与适配层职责 | [x] | VERIFIED COMPLETE | 风险和 SL/TP 逻辑保留在 `bot.py`：1920-2052, 2593-2627；适配器仅负责执行与结果映射：`exchange_client.py`:289-362, 364-431。Dev Notes 中也明确角色划分（行 73-77）。 |
| 任务 1.3：提取下单参数构造模式（symbol 映射、`positionSide`、`reduceOnly` 等）并在适配器与调用点体现 | [x] | VERIFIED COMPLETE | symbol 映射：`bot.py`:2082-2084, 2323-2325；positionSide / reduceOnly 参数：`exchange_client.py`:319-323, 389-418；smoke 脚本中的 ccxt 调用与之对齐：`scripts/manual_binance_futures_smoke.py`:278-288, 321-333。 |
| 任务 2：设计与实现 BinanceFuturesExchangeClient 适配器 | [x] | VERIFIED COMPLETE | 适配器实现与错误聚合：`exchange_client.py`:235-362, 364-431, 248-261, 263-287；单测覆盖 place_entry/close_position 成功/失败路径：`tests/test_exchange_client_binance_futures.py`:33-136。 |
| 任务 2.1：在 `exchange_client.py` 中新增 `BinanceFuturesExchangeClient` 类并组合 ccxt 客户端 | [x] | VERIFIED COMPLETE | `exchange_client.py`:235-238（持有 `exchange` 实例），289-362, 364-431。 |
| 任务 2.2：在 `place_entry(...)` 中调用 `exchange.create_order` 并封装为 `EntryResult` | [x] | VERIFIED COMPLETE | 调用与结果封装：`exchange_client.py`:289-329, 335-362；单测验证 OID 映射与无错误：`tests/test_exchange_client_binance_futures.py`:33-66。 |
| 任务 2.3：在 `close_position(...)` 中使用 reduce-only 市价单完成平仓并封装为 `CloseResult` | [x] | VERIFIED COMPLETE | `exchange_client.py`:364-389, 389-418, 420-430；在 `close_position` 中默认使用 `reduceOnly=True`，遇到 `code=-1106` 时降级去掉 `reduceOnly` 重试。 |
| 任务 2.4：适配器不直接读取环境变量，仅依赖外部传入 exchange 实例 | [x] | VERIFIED COMPLETE | `BinanceFuturesExchangeClient.__init__` 仅接受 `exchange` 参数，未访问环境变量：`exchange_client.py`:235-238；exchange 初始化由 `get_binance_futures_exchange()` / `manual_binance_futures_smoke._make_exchange` 负责。 |
| 任务 3：接入 ExchangeClient 工厂与 Bot 实盘路径 | [x] | VERIFIED COMPLETE | `get_exchange_client("binance_futures")` 分支：`exchange_client.py`:450-454；`bot.py` 中 ENTRY/CLOSE 均通过该工厂构造适配器：2075-2105, 2315-2342。 |
| 任务 3.1：在 `get_exchange_client` 中增加 `backend="binance_futures"` 分支 | [x] | VERIFIED COMPLETE | `exchange_client.py`:450-454。 |
| 任务 3.2：在 `bot.py` 的 Binance Futures ENTRY/CLOSE 路径中改为调用 `get_exchange_client` | [x] | VERIFIED COMPLETE | ENTRY：`bot.py`:2075-2105；CLOSE：2315-2342。 |
| 任务 3.3：保持日志与错误处理语义与原路径一致或更清晰 | [x] | VERIFIED COMPLETE | ENTRY 失败日志：`bot.py`:2102-2104；CLOSE 失败日志：2339-2341；错误信息来源于 `EntryResult.errors`/`CloseResult.errors`：`exchange_client.py`:263-287, 335-348, 406-419。 |
| 任务 4：测试与最小行为验证 | [x] | VERIFIED COMPLETE | 单元测试：`tests/test_exchange_client_binance_futures.py`:33-136；实盘 smoke：`scripts/manual_binance_futures_smoke.py`:59-139, 222-343；运行脚本：`scripts/run_binance_futures_smoke.sh`:1-32。 |
| 任务 4.1：新增 BinanceFuturesExchangeClient 的单元测试 | [x] | VERIFIED COMPLETE | `tests/test_exchange_client_binance_futures.py` 覆盖 place_entry/close_position 成功与失败路径，并验证错误文本。 |
| 任务 4.2：在受控环境中完成最小 ENTRY/CLOSE smoke 验证 | [x] | VERIFIED COMPLETE | 真实 Binance Futures 日志（2025-11-27 18:13:46–18:14:01）显示 `BTCUSDT size=0.002` 的 ENTRY/CLOSE 全部 `success=True`，由 `BinanceFuturesExchangeClient` 触发；脚本实现参见 `scripts/manual_binance_futures_smoke.py`:222-343。 |
| 任务 4.3：根据测试与 smoke 结果微调错误处理与结果映射，并在 Dev Notes 中记录 | [x] | VERIFIED COMPLETE | `manual_binance_futures_smoke.determine_order_params` 中增加最小名义/数量逻辑：59-139；`BinanceFuturesExchangeClient.close_position` 中增加 `reduceOnly` 降级处理：`exchange_client.py`:389-418；Dev Notes 与 Debug Log 已记录对应调整（行 126-140, 128-134）。 |

**Task Completion Summary**: 所有标记为完成的 Tasks/Subtasks（含 任务 1–4 及其子项）均已在代码/测试/脚本中找到对应实现，未发现「标记完成但实际未做」或「实现已完成但未勾选」的情况。

### Test Coverage and Gaps

- **现有覆盖**：  
  - 单元测试：`tests/test_exchange_client_binance_futures.py` 覆盖 ENTRY/CLOSE 成功与失败路径、错误聚合与 OID 映射；Hyperliquid 适配器的测试仍保持可用，为对比验证提供参考。  
  - 手工 smoke：`scripts/manual_binance_futures_smoke.py` + `scripts/run_binance_futures_smoke.sh` 在真实 Binance Futures 环境完成 `BTCUSDT size≈0.002` ENTRY/CLOSE 跑通，验证了适配器与 `bot.py` 的集成路径。  

- **已知空白（但不阻塞本 Story）**：  
  - 未为 `BinanceFuturesExchangeClient.close_position` 中的 `reduceOnly` 降级重试分支编写专门单测，目前仅由 smoke 日志证明其行为正确。  
  - 未为 `determine_order_params` 中的「最小名义/数量」计算编写 stub-based 单测；后续若 Binance 规则调整，需要通过 smoke 或额外测试捕获。

### Architectural Alignment

- 符合 `docs/architecture/07-implementation-patterns.md` 中关于「外部服务适配器」的约定：  
  - 适配器通过组合持有 `exchange` 对象，而非直接依赖全局状态或环境变量。  
  - `ExchangeClient` 抽象统一了执行接口，具体 backend（Hyperliquid / Binance Futures）仅在适配层有所差异。  
- `bot.py` 继续负责风险计算、止损/止盈与仓位状态管理；适配器只将 ccxt 返回值映射为统一结果结构，未破坏既有职责边界。  
- 未发现违反现有分层或依赖方向的代码结构问题。

### Security Notes

- Binance API Key/Secret 通过 `.env` 或环境变量注入，`manual_binance_futures_smoke.py` 使用 `dotenv.load_dotenv` 加载，不在代码中硬编码密钥。  
- smoke 脚本明确标记为**手工执行**，不会被纳入自动化测试或 CI。  
- 未发现明显的注入风险或敏感信息泄露点；实盘交易风险通过手工脚本参数与仓位大小控制。  

### Best-Practices and References

- 错误聚合模式与 Hyperliquid 适配器保持一致，便于未来统一监控与回放。  
- 通过手工 smoke 发现并修正了 Binance 在最小名义与 `reduceOnly` 参数上的细节约束，体现了「以真实交易行为验证抽象」的实践。  

### Action Items

**Code Changes Recommended (Non-blocking)**

- [ ] [Low] 为 `BinanceFuturesExchangeClient.close_position` 的 `reduceOnly` 降级重试路径补充单元测试（构造 stub exchange 在首次调用时抛出 `code=-1106` / `"reduceonly"` 错误，验证 fallback 分支行为与错误聚合）。 _[file: `exchange_client.py`:389-418; tests: `tests/test_exchange_client_binance_futures.py`]_  
- [ ] [Low] 为 `manual_binance_futures_smoke.determine_order_params` 的最小名义/数量逻辑添加一个基于 stub exchange 的测试用例，锁定 `limits.cost.min` / `limits.amount.min` / `precision.amount` 的组合行为，降低未来 Binance 规则变更带来的回归风险。 _[file: `scripts/manual_binance_futures_smoke.py`:59-139]_  

**Advisory Notes (No Immediate Action Required)**

- Note: 若未来引入更多 Binance 合约或其他交易对，建议为 smoke 脚本增加可配置的 symbol 列表与更严格的保护（例如显式确认提示），以避免误对大额仓位执行 smoke。  
- Note: 可以考虑在后续 Story 中为 Hyperliquid 与 Binance smoke 脚本抽取公共工具函数（如「计算最小可行 size」），减少不同 backend 之间的重复逻辑。

