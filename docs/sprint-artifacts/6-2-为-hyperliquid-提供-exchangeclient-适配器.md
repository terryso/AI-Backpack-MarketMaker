# Story 6.2: 为 Hyperliquid 提供 ExchangeClient 适配器
 
Status: in-progress

## Story

As a developer maintaining Hyperliquid live trading,
I want HyperliquidTradingClient to be wrapped behind the unified ExchangeClient interface,
So that Hyperliquid live execution can be used transparently by the bot.

本故事的目标是：在不改变现有 Hyperliquid 实盘行为的前提下，基于既有 `HyperliquidTradingClient` 实现一个符合 `ExchangeClient` 抽象的 Hyperliquid 专用适配器，使 Bot 在调用层面对交易所无感知，为后续多交易所支持与执行层重构打下基础。

## Acceptance Criteria

1. **实现 HyperliquidExchangeClient 适配器（AC1）**  
   - 提供一个实现 `ExchangeClient` 协议/接口的适配器类（命名建议：`HyperliquidExchangeClient` 或等价），位于 `exchange_client.py` 或等价模块中。  
   - `place_entry(...)` 接口参数与 `ExchangeClient.place_entry` 对齐，内部委托给 `HyperliquidTradingClient.place_entry_with_sl_tp`（或等价调用路径），传递 coin/symbol、side、size、entry_price、stop_loss_price、take_profit_price、leverage、liquidity 等核心参数。  
   - `close_position(...)` 与 `ExchangeClient.close_position` 对齐，内部委托给 Hyperliquid 当前平仓路径（例如 `HyperliquidTradingClient.close_position`），支持全仓/部分平仓。  

2. **统一结果结构映射到 EntryResult / CloseResult（AC2）**  
   - 对 Hyperliquid 下单 / 平仓的原始响应进行解析，并映射到 `EntryResult` / `CloseResult`：  
     - `backend="hyperliquid"`；  
     - `success` 由 Hyperliquid 响应的 `status` 与订单状态字段（filled/resting 等）综合判定；  
     - 将错误信息（拒单、异常等）汇总到 `errors: list[str]` 中，避免仅 dump 原始异常字符串；  
     - 在可能的情况下，从响应结构中提取 `entry_oid` / `tp_oid` / `sl_oid` / `close_oid` 等订单 ID，并填入结果对象；  
     - 将完整原始响应放入 `raw`，方便后续调试与日志分析。  

3. **保持现有 Hyperliquid 行为与体验不变（AC3）**  
   - 适配器层仅负责封装与结果映射，不改变 `HyperliquidTradingClient` 内部的：  
     - tick size 归一化逻辑；  
     - 触发单（SL/TP）下单方式；  
     - `is_live` / 初始化与错误处理语义。  
   - 在 `TRADING_BACKEND` / Hyperliquid 实盘开关的组合下，通过最小验证（例如 `scripts/manual_hyperliquid_smoke.py` 或等价脚本）确认： 
     - 使用适配器后的行为与当前直接调用 `HyperliquidTradingClient` 的路径在结果和日志语义上等价；  
     - 发生错误时 `errors` 字段能够提供足够清晰的诊断信息，同时 `raw` 中仍保留原始响应。  

## Tasks / Subtasks

- [x] 任务 1：梳理 Hyperliquid 现有执行路径与 ExchangeClient 抽象（AC: #1, #2, #3）  
  - [x] 通读 `hyperliquid_client.HyperliquidTradingClient`，重点关注 `place_entry_with_sl_tp`、（如有）`close_position` 以及返回结构中与订单状态/错误信息相关的字段。  
  - [x] 对照 `exchange_client.EntryResult` / `CloseResult` 与 Story 6.1 文档，列出需要从 Hyperliquid 原始响应中映射到统一结果结构的关键字段（success/backend/errors/oid/raw/extra）。  
  - [x] 结合 `docs/prd.md` 4.8「Hyperliquid 实盘集成」与 `docs/architecture/03-data-flow.md` / `04-integrations.md`，确认在本 Story 范围内不应改变的行为与边界（例如：实盘开关、错误回退到纸上交易等）。  

- [x] 任务 2：设计与实现 HyperliquidExchangeClient 适配器（AC: #1, #2）  
  - [x] 在 `exchange_client.py`（或等价模块）中新增 `HyperliquidExchangeClient` 类，实现 `ExchangeClient` 协议，并通过组合（而非继承）持有一个 `HyperliquidTradingClient` 实例。  
  - [x] 在 `place_entry(...)` 中调用 `HyperliquidTradingClient.place_entry_with_sl_tp`，并将返回结果安全地解析为 `EntryResult`：包含 `success`、`backend`、`errors`、`entry_oid` / `tp_oid` / `sl_oid`、`raw`、`extra` 等。  
  - [x] 在 `close_position(...)` 中调用对应的 Hyperliquid 平仓方法，将返回值封装为 `CloseResult`，并对错误与异常做统一处理。  

- [ ] 任务 3：接入与最小行为验证（AC: #2, #3）  
  - [ ] 在合适的位置（例如 `exchange_client.get_exchange_client` 或 Bot 的初始化路径）为 `backend="hyperliquid"` 场景返回 `HyperliquidExchangeClient` 实例，但避免在本 Story 内对 `execute_entry` / `execute_close` 做大规模重构（留给 Story 6.4）。  
  - [ ] 通过最小 smoke 测试（例如基于 `scripts/manual_hyperliquid_smoke.py` 或新建一个轻量脚本）验证：在典型 ENTRY/CLOSE 路径下，适配器封装前后对 Hyperliquid 的实际行为等价。  
  - [ ] 检查日志与错误信息：确认 `EntryResult` / `CloseResult` 的 `errors` 字段为上层调用提供了比原始响应更清晰的诊断语义，而不会丢失关键信息。  

- [ ] 任务 4：文档与架构映射对齐（AC: #3）  
  - [ ] 在本 Story 文档的 Dev Notes / Project Structure Notes 中补充 Hyperliquid 适配器与 Epic 6、PRD 4.8 以及架构 06/07 章节的映射关系。  
  - [ ] 如有必要，在 `docs/architecture/06-project-structure-and-mapping.md` 或相关文档中补充一条关于 Exchange Execution Layer 与 Hyperliquid 适配器的条目。  

## Dev Notes

- 本 Story 基于 Story 6.1 中引入的 `ExchangeClient` 抽象与 `EntryResult` / `CloseResult` 统一结果结构，聚焦于将现有 `HyperliquidTradingClient` 封装到统一执行层下，而不改变其内部撮合与 tick size/触发单行为。  
- 实现时应遵守 `docs/architecture/07-implementation-patterns.md` 中的外部服务适配模式：  
  - 适配器本身不直接读取环境变量或进行复杂初始化，而是依赖已有的 Hyperliquid 初始化流程；  
  - 所有对外可见的行为变化（例如错误信息格式）需在 Dev Notes 中记录，以便后续 Story（6.3–6.5）复用。  
- 结果结构中的 `errors` 字段应面向「人类开发者与日志阅读者」设计，避免仅复制 SDK 原始异常文本；`raw` 字段则保留完整 payload，满足调试与回放需求。  

### Learnings from Previous Story (Story 6.1)

- Story 6.1 已在 `exchange_client.py` 中定义：  
  - 统一的 `ExchangeClient` 协议，明确了 `place_entry` / `close_position` 的参数与返回值语义；  
  - `EntryResult` / `CloseResult` 数据结构，提供 `success`、`backend`、`errors`、OID 字段与 `raw`/`extra` 扩展点。  
- 本 Story 在实现 Hyperliquid 适配器时应：  
  - 复用既有的 `EntryResult` / `CloseResult` 定义，不在本 Story 中新增字段或破坏其语义；  
  - 避免在适配器中直接修改 Hyperliquid 客户端的错误处理逻辑，而是通过结果映射层统一对外暴露语义一致的错误信息；  
  - 为后续 Binance Futures 适配器与 `execute_entry` / `execute_close` 重构（Story 6.3 / 6.4）保留清晰、可复用的接口与映射模式。  

### Project Structure Notes

- 建议在现有 `exchange_client.py` 模块中新增 `HyperliquidExchangeClient` 实现，使其与 `ExchangeClient` 接口及结果结构位于同一适配层，便于搜索与维护。  
- 若未来为多交易所适配扩展出子模块结构（例如 `exchange_clients/hyperliquid.py` / `exchange_clients/binance_futures.py`），应在架构文档中更新对应的项目结构示意，并保持 `ExchangeClient` 抽象仍位于统一入口模块。  
- 不新增额外的顶层运行脚本；所有实盘行为仍通过 `bot.py` 与现有 smoke 测试脚本驱动。  

### References

- Epics：`docs/epics.md` 中 "Story 6.2: 为 Hyperliquid 提供 ExchangeClient 适配器" 章节。  
- PRD：`docs/prd.md` 4.8「Hyperliquid 实盘集成」及 4.1/4.2 关于主循环与风险控制的约束。  
- 架构：  
  - `docs/architecture/03-data-flow.md`：LLM 决策到执行层的数据流；  
  - `docs/architecture/04-integrations.md`：Hyperliquid 等外部服务集成点；  
  - `docs/architecture/06-project-structure-and-mapping.md`：Hyperliquid 集成与源码树映射；  
  - `docs/architecture/07-implementation-patterns.md`：外部服务适配与错误处理模式。  
- 代码：  
  - `exchange_client.py`：`ExchangeClient` 抽象与 `EntryResult` / `CloseResult` 定义；  
  - `hyperliquid_client.py`：`HyperliquidTradingClient` 的现有实盘执行逻辑；  
  - `docs/sprint-artifacts/6-1-定义-exchangeclient-抽象接口与统一结果结构.md`：上一 Story 的实现与评审记录。  

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/6-2-为-hyperliquid-提供-exchangeclient-适配器.context.xml`  

### Agent Model Used

- Cascade / dev agent "Amelia"（通过 `/dev` → `*develop-story*` 工作流执行，模型：Cascade）  

### Debug Log References

- 2025-11-27：通读 `hyperliquid_client.HyperliquidTradingClient` 与 Story 6.1 / 6.2 的 context XML，梳理 Hyperliquid 实盘执行路径、订单 ID 与错误结构，为适配器设计准备输入（AC #1, #2, #3）。  
- 2025-11-27：在 `exchange_client.py` 中新增 `HyperliquidExchangeClient` 实现，并实现 `get_exchange_client("hyperliquid", trader=...)` 分支，将 Hyperliquid 开仓/平仓结果封装为统一的 `EntryResult` / `CloseResult`（AC #1, #2）。  
- 2025-11-27：新增 `tests/test_exchange_client_hyperliquid.py`，为 `HyperliquidExchangeClient.place_entry` / `close_position` 编写单元测试，并执行 `python -m unittest tests.test_exchange_client_hyperliquid` 验证结果映射逻辑（AC #2）。  

### Completion Notes List

- 已完成 AC #1 / #2 相关工作：实现 `HyperliquidExchangeClient` 适配器与针对 EntryResult / CloseResult 映射的单元测试，当前仍未在生产路径中接线，Hyperliquid 实盘行为保持不变（Story 状态为 `in-progress`）。  
- 已在 `scripts/manual_hyperliquid_smoke.py` 中增加可选的 `--use-exchange-client` 开关，用于在真实 Hyperliquid 环境下通过 `HyperliquidExchangeClient` 执行一次典型 ENTRY/CLOSE 路径的端到端 smoke 测试，从而验证适配器封装前后行为等价（AC #3 的技术路径已打通）。  
- 由于当前环境尚未配置有效的 `HYPERLIQUID_WALLET_ADDRESS` / `HYPERLIQUID_PRIVATE_KEY`，AC #3 仅完成到「适配器 + 单测 + smoke 脚本 wiring」阶段，端到端 live 验证暂时被外部环境阻塞；后续在配置好 Hyperliquid 钱包后，建议运行如下命令完成验证并在本 Story 中更新记录：  
  - `python scripts/manual_hyperliquid_smoke.py --coin BTC --notional 2 --leverage 1 --wait 15 --sl-bps 200 --tp-bps 200 --use-exchange-client`  
- 后续工作包括：在合适位置集成 `get_exchange_client("hyperliquid")`（预计在 Story 6.4 中重构 `execute_entry` / `execute_close`），以及在完成 Hyperliquid 凭证配置后，执行上面的 smoke 测试并根据结果更新本 Story 的 AC3/任务 3 状态。  

### File List

- `exchange_client.py`：修改。新增 `HyperliquidExchangeClient` 实现与 `get_exchange_client("hyperliquid")` 分支，将 `HyperliquidTradingClient` 的开仓/平仓聚合响应映射为统一的 `EntryResult` / `CloseResult` 结构（AC #1, #2）。  
- `tests/test_exchange_client_hyperliquid.py`：新增。为 HyperliquidExchangeClient 的 `place_entry` / `close_position` 编写单元测试，覆盖成功与失败路径，验证 `success` / `backend` / `errors` / OID / `raw` / `extra` 字段语义（AC #2）。  
- `docs/sprint-artifacts/sprint-status.yaml`：修改。将 Story `6-2-为-hyperliquid-提供-exchangeclient-适配器` 的开发状态从 `ready-for-dev` 更新为 `in-progress`，与当前 Dev Story 工作流执行状态保持一致。  

## Change Log

- [ ] 2025-11-27：初始 Story 草稿由 Scrum Master 根据 epics/PRD/架构文档与 Story 6.1 的 Dev Notes 生成，状态设为 `drafted`。
- [ ] 2025-11-27：实现 `HyperliquidExchangeClient` 适配器与对应单元测试，更新 `scripts/manual_hyperliquid_smoke.py` 以支持 `--use-exchange-client` 模式，并将 sprint-status.yaml 中本 Story 状态更新为 `in-progress`；本 Story 当前完成 AC #1 / #2，AC #3 因缺少 Hyperliquid 凭证暂时仅停留在「适配器 + 单测 + smoke wiring」阶段，待未来补充 live smoke 验证后再更新为完成。
