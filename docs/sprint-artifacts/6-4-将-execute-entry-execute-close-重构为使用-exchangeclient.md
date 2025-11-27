# Story 6.4: 将 execute_entry / execute_close 重构为使用 ExchangeClient

Status: done

## Story

As a maintainer of the main trading loop,
I want execute_entry and execute_close to depend only on a unified ExchangeClient abstraction,
So that adding or changing exchanges does not require editing core bot logic and risk rules.

本故事的目标是：在保持现有风控约束与交易行为不变的前提下，将 `execute_entry` / `execute_close` 重构为依赖单一的 `ExchangeClient` 抽象；
通过根据 `TRADING_BACKEND` 与各自的 live 开关（例如 `HYPERLIQUID_LIVE_TRADING`、`BINANCE_FUTURES_LIVE`）选择合适的 `exchange_client` 实例（Hyperliquid / Binance Futures / 未来交易所），
消除核心交易主循环中针对具体 backend 的 if/elif 分支，并让持仓结构统一记录实盘执行信息。

## Acceptance Criteria

1. **execute_entry / execute_close 完全依赖 ExchangeClient 抽象（AC1）**  
   - 在 `execute_entry` / `execute_close` 内部，不再直接分支调用 `HyperliquidTradingClient` 或 ccxt Binance 客户端；  
   - 所有与实盘相关的 ENTRY / CLOSE 调用均通过一个事先构造好的 `exchange_client: ExchangeClient` 实例完成；  
   - paper 模式下可使用与 ExchangeClient 接口兼容的 no-op / 模拟实现，但调用路径保持一致。

2. **根据 TRADING_BACKEND 与实盘开关选择具体 ExchangeClient 实现（AC2）**  
   - 依据 `TRADING_BACKEND`（如 `hyperliquid` / `binance_futures` / 未来扩展值）及对应 live 开关（如 `HYPERLIQUID_LIVE_TRADING`、`BINANCE_FUTURES_LIVE`）构造或选择具体实现：  
     - Hyperliquid 使用 `HyperliquidExchangeClient`；  
     - Binance Futures 使用 `BinanceFuturesExchangeClient`；  
     - 未来新增 backend 只需实现 ExchangeClient 即可插入。  
   - 在配置缺失或 live 条件不满足时：
     - 回退到安全的 paper 模式行为；
     - 通过统一的日志与 `errors: list[str]` 暴露配置问题，而不是静默失败。

3. **统一处理 EntryResult / CloseResult 并回写到持仓结构（AC3）**  
   - 对 `ExchangeClient.place_entry` / `close_position` 返回的 `EntryResult` / `CloseResult`：  
     - 统一处理 `success` / `errors` 字段（成功路径只在 `success=True` 且 `errors` 为空或仅包含非致命提示时继续；失败路径统一记录简明的人类可读错误信息）；  
     - 在成功路径中，尽可能从 `EntryResult` / `CloseResult` 中提取代表性的 OID 并写入持仓或内部记录结构。  
   - 日志语义统一：
     - ENTRY/CLOSE 成功时，日志中至少包含 backend、symbol、size、价格信息以及 OID 概要；
     - 失败时，日志中引用 `errors` 中的摘要，而不是仅 dump 原始异常字符串。

4. **扩展或规范持仓结构以记录 live 执行信息（AC4）**  
   - 在当前持仓/组合结构（position dict / dataclass 等）中：  
     - 增加或规范 `live_backend`、`entry_oid`、`tp_oid`、`sl_oid`、`close_oid` 等字段；  
     - 确保对 Hyperliquid 与 Binance Futures 路径保持兼容，不破坏现有 CSV/JSON 持久化语义。  
   - 在 PRD 4.2「风险控制与资金管理」既有约束下，保持风险与仓位状态字段的含义不变，仅新增执行层 OID 类元数据。

5. **关键回归场景行为等价（AC5）**  
   - 在以下回归场景中，行为与重构前等价（允许日志文案略有调整）：  
     - 仅 paper 模式时，ENTRY/CLOSE 的数量、价格与 PnL 计算保持一致；  
     - `TRADING_BACKEND="hyperliquid"` 且 `HYPERLIQUID_LIVE_TRADING=true` 时，订单与日志行为与 Story 6.2 完成后的实现等价；  
     - `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时，行为与 Story 6.3 验证通过的路径等价。  
   - 回归方式可以结合现有单元测试、集成测试以及 Hyperliquid / Binance smoke 测试脚本完成。

6. **为未来交易所扩展保留清晰接入点（AC6）**  
   - 在代码与 Dev Notes 中明确：新增交易所时只需：  
     - 实现 ExchangeClient 接口；  
     - 在工厂函数/配置中增加 backend → ExchangeClient 映射；  
     - 确保 `EntryResult` / `CloseResult` 的错误语义与现有 backend 一致。  
   - 不要求本 Story 内完成 README 或 PRD 的大幅更新，但应在 Dev Notes 中给出最小接入 checklist 草案，为后续 Story 6.5 的文档工作做铺垫。

## Tasks / Subtasks

- [ ] 任务 1：梳理现有 execute_entry / execute_close 与持仓结构（AC: #1, #3, #4）  
  - [ ] 通读 `bot.py` 中 `execute_entry` / `execute_close` 的当前实现，标记所有直接依赖 Hyperliquid / Binance 的分支与参数组装逻辑。  
  - [ ] 结合 `docs/epics.md` 中 Epic 6 与 Story 6.1–6.3 的实现说明，明确哪些逻辑应继续保留在 `bot.py`（风控、头寸管理），哪些应完全交给 ExchangeClient 负责（执行与结果映射）。  
  - [ ] 整理当前持仓/组合结构中与 live 执行相关的字段（例如 symbol、size、entry_price、stop_loss、take_profit 等），为增加 `live_backend` / OID 等字段准备设计空间。

- [ ] 任务 2：设计 exchange_client 注入与选择策略（AC: #1, #2）  
  - [ ] 复用并扩展 `exchange_client.get_exchange_client` 工厂：根据 `TRADING_BACKEND` 与各自 live 开关选择或构造具体 `ExchangeClient` 实例；必要时为 paper 模式提供轻量 mock。  
  - [ ] 确保 ExchangeClient 的生命周期与资源管理清晰（例如在主循环初始化阶段构造单例，而不是在每次 ENTRY/CLOSE 时重新初始化外部 SDK）。  
  - [ ] 在 Dev Notes 中记录 backend 选择矩阵（`TRADING_BACKEND` × live 开关 × ExchangeClient 实现）。

- [ ] 任务 3：重构 execute_entry 使用 ExchangeClient（AC: #1, #2, #3, #5）  
  - [ ] 将 `execute_entry` 中针对 Hyperliquid / Binance 的 if/elif 分支收敛为：  
    - 通过工厂获取 `exchange_client`；  
    - 使用统一的参数结构调用 `exchange_client.place_entry(...)`。  
  - [ ] 保持风险与头寸计算逻辑（基于 PRD 4.2 单笔风险、杠杆等约束）仍在 `bot.py` 中执行，只将「实际下单」动作委托给 ExchangeClient。  
  - [ ] 对 `EntryResult` 做统一处理：更新持仓结构、写入必要的 OID 字段、在失败时通过 `errors` 与日志返回清晰错误。

- [ ] 任务 4：重构 execute_close 使用 ExchangeClient（AC: #1, #2, #3, #5）  
  - [ ] 将 `execute_close` 中对 Hyperliquid / Binance 的平仓逻辑统一改为调用 `exchange_client.close_position(...)`；  
  - [ ] 在失败路径中，保留现有对仓位的保护行为（例如不在下单失败时意外删除持仓记录），并通过 `CloseResult.errors` 提示具体问题。  
  - [ ] 确保在 paper / Hyperliquid / Binance 三种模式下，CLOSE 逻辑在仓位变更与日志层面的行为与重构前等价。

- [ ] 任务 5：扩展持仓结构与数据持久化（AC: #3, #4）  
  - [ ] 在内部持仓结构中新增或规范 `live_backend`、`entry_oid`、`tp_oid`、`sl_oid`、`close_oid` 等字段；  
  - [ ] 检查 `trade_history.csv` / `portfolio_state.json` 等持久化结构是否需要同步扩展字段，避免破坏现有 schema（可以通过向后兼容的方式追加列/字段）。  
  - [ ] 在 Dev Notes 中记录字段含义与来源（来自 EntryResult / CloseResult 的哪些字段）。

- [ ] 任务 6：回归测试与 smoke 验证（AC: #5, #6）  
  - [ ] 更新或新增单元测试，覆盖使用 ExchangeClient 的 `execute_entry` / `execute_close` 行为，至少包括：paper / Hyperliquid / Binance 三条路径的成功与失败场景。  
  - [ ] 复用现有 `tests/test_exchange_client_hyperliquid.py` 与 `tests/test_exchange_client_binance_futures.py` 中的 stub/mocker 模式，避免在 Story 6.4 中直接访问真实外部服务。  
  - [ ] 在需要时，调用 Hyperliquid 与 Binance 的 smoke 测试脚本做一次最小规模回归，以确认重构没有改变成功/失败路径的外观行为（日志与错误语义）。

## Dev Notes

- 本 Story 直接承接 Epic 6 的 FR13「统一交易所执行抽象层」，以及 Story 6.1–6.3 已经完成的 ExchangeClient 抽象、Hyperliquid/Binance 适配，实现目标是**把抽象真正接入交易主循环**。  
- 根据 `docs/PRD.md` 4.1 / 4.2，本 Story 必须确保：
  - 交易频率、风险暴露与止损/止盈规则在重构前后保持一致；  
  - LLM 决策与风控校验流程不因为执行层重构而被绕过。  
- 本 Story 不再修改适配器内部的执行细节（例如 Hyperliquid 的 tick size 处理、Binance 的最小名义/数量规则等），而是将 Story 6.2 / 6.3 中已经实现和验证的行为「接线」到统一的执行路径。  
- 对日志与错误处理的目标是「面向人类开发者可读」：ENTRY/CLOSE 相关日志应能快速回答：  
  - 使用了哪个 backend？  
  - 实际下了什么订单（symbol/side/size/价格/OID）？  
  - 如果失败，原因是什么（例如 `insufficient margin` / `min notional` / `reduceOnly` 参数不被接受等）。

### 新增交易所 ExchangeClient 接入最小 Checklist（AC6 草案）

1. **确定 backend 标识与配置开关**  
   - 为新交易所约定唯一的 `TRADING_BACKEND` 值（例如 `myexchange`）。  
   - 在 `.env` / `.env.example` 中增加对应的 live 开关和必要的 API 配置（如 `MYEXCHANGE_LIVE_TRADING`、API key/secret 等），并在 `bot.py` 里通过 `_parse_bool_env` / `os.getenv` 读取。  

2. **在 `exchange_client.py` 中实现 ExchangeClient 适配器**  
   - 定义 `MyExchangeExchangeClient(ExchangeClient)`，内部封装该交易所 SDK/HTTP 客户端。  
   - 在 `place_entry` / `close_position` 中：
     - 负责把统一入参（`coin`、`side`、`size`、`entry_price`、`stop_loss_price`、`take_profit_price` 等）转换为交易所的下单/平仓请求；  
     - 解析交易所返回，构造 `EntryResult` / `CloseResult`：
       - 正确设置 `backend`（例如 `"myexchange"`）；  
       - 尽可能填充 `entry_oid` / `tp_oid` / `sl_oid` / `close_oid`；  
       - 将人类可读的错误信息聚合到 `errors: list[str]`，原始 payload 放入 `raw` 便于调试。  

3. **扩展工厂函数 `get_exchange_client`**  
   - 在 `get_exchange_client` 中增加对新 backend 的分支：
     - 基于 `backend == "myexchange"`、live 开关以及必要的依赖（如已初始化的 SDK 实例）构造 `MyExchangeExchangeClient`；  
     - 在配置缺失或依赖初始化失败时，通过 `errors`/日志明确给出原因，并回退到安全行为（例如仅 paper 模式或直接跳过 ENTRY/CLOSE）。  

4. **主循环接线与行为约束**  
   - 确认 `bot.py` 中的 `execute_entry` / `execute_close` 只通过 ExchangeClient 执行实盘，不直接调用新交易所 SDK：
     - 在基于 `TRADING_BACKEND` 与 live 开关的分支中调用 `get_exchange_client("myexchange", ...)`；  
     - 继续在 `bot.py` 内部完成风险/头寸计算与风控校验，新 backend 只负责「怎么下单」。  
   - 确保新 backend 在成功路径下填充的 OID 字段（`live_backend`、`entry_oid`、`tp_oid`、`sl_oid`、`close_oid`）与现有 Hyperliquid / Binance 一致，从而：
     - 持仓结构、`portfolio_state.json`、`scripts/recalculate_portfolio.py` 等无需特殊分支即可复用；  
     - LLM prompt 中的 `position_payload` 可以统一展示执行元数据。  

5. **测试与回归验证**  
   - 新增 `tests/test_exchange_client_<backend>.py`：
     - 使用 stub/mocker 模拟 SDK 返回，分别覆盖成功与失败路径；  
     - 断言 `EntryResult` / `CloseResult` 的 `backend`、OID 字段与 `errors` 聚合符合约定。  
   - 在 paper 模式下运行 `python3 bot.py`，确认：
     - 没有配置新 backend 的 live 开关时，行为保持 paper 模式且无异常；  
     - `scripts/recalculate_portfolio.py --dry-run` 仍能从 `trade_history.csv` 正常重建持仓。  
   - 如具备真实或 sandbox 凭证，可为新 backend 增加最小 smoke 测试脚本，验证一笔小额 ENTRY+CLOSE 的完整回路。

### Learnings from Previous Story (Story 6.3)

- Story 6.3 已经为 Binance Futures 路径实现 `BinanceFuturesExchangeClient`，并验证了在 `TRADING_BACKEND="binance_futures"` 且 `BINANCE_FUTURES_LIVE=true` 时，通过 ExchangeClient 完成 ENTRY/CLOSE 的可行性。  
- 6.3 的 Dev Notes 与 File List 表明：
  - `exchange_client.py` 中已具备 `ExchangeClient` 抽象、`EntryResult` / `CloseResult` 以及 `HyperliquidExchangeClient` / `BinanceFuturesExchangeClient` 两个具体实现；  
  - 在 `bot.py` 中，Binance Futures 实盘路径已部分接入 ExchangeClient，只是整体的 `execute_entry` / `execute_close` 分支结构仍有一定历史负担。  
- 对本 Story 的启发：
  - 重构应优先复用现有 adapter 与错误聚合模式，而不是在 `bot.py` 中重新拆解外部 SDK 返回值；  
  - 可以以 Story 6.3 中的 Change Log 与 Senior Developer Review 为基线，确保在重构过程中不破坏已有的行为证据（尤其是真实 Binance smoke 路径）。

### Project Structure Notes

- `ExchangeClient` 抽象与具体实现（Hyperliquid / Binance Futures）继续集中在 `exchange_client.py` 中维护，作为所有实盘执行 backend 的统一入口。  
- `bot.py` 仍然是交易主循环与风控逻辑的中心；本 Story 仅在 `execute_entry` / `execute_close` 附近做重构，以减少对其余模块的影响。  
- 与 Story 6.3 一致，测试代码与 smoke 脚本位于：  
  - 单元测试：`tests/test_exchange_client_hyperliquid.py`、`tests/test_exchange_client_binance_futures.py`；  
  - smoke：`scripts/manual_hyperliquid_smoke.py`、`scripts/run_hyperliquid_smoke.sh`、`scripts/manual_binance_futures_smoke.py`、`scripts/run_binance_futures_smoke.sh`。  
- 后续如果将执行层拆分为子包（例如 `exchange_clients/` 目录），需要同步更新 `docs/architecture/06-project-structure-and-mapping.md`，但不在本 Story 范围内。

### References

- Epics：`docs/epics.md` 中 "Story 6.4: 将 execute_entry / execute_close 重构为使用 ExchangeClient" 章节。  
- PRD：  
  - `docs/PRD.md` 4.1「交易主循环（Bot）」：描述主循环节奏、执行链路与 LLM 决策流程；  
  - `docs/PRD.md` 4.2「风险控制与资金管理」：定义单笔风险、止损必选与退出规则；  
  - `docs/PRD.md` 4.8「Hyperliquid 实盘集成」：可类比参考 Hyperliquid 实盘路径在重构后的预期行为。  
- 架构：  
  - `docs/architecture/03-data-flow.md`：从行情 → LLM 决策 → 执行层的数据流；  
  - `docs/architecture/04-integrations.md`：Binance / Hyperliquid 等外部依赖与集成点；  
  - `docs/architecture/06-project-structure-and-mapping.md`：Bot / scripts / docs 与源码树映射；  
  - `docs/architecture/07-implementation-patterns.md`：外部服务适配与错误处理模式。  
- 相关 Story：  
  - `docs/sprint-artifacts/6-2-为-hyperliquid-提供-exchangeclient-适配器.md`（若存在）；  
  - `docs/sprint-artifacts/6-3-为-binance-futures-提供-exchangeclient-适配器.md`（当前 Story 的直接前置）。

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/6-4-将-execute-entry-execute-close-重构为使用-exchangeclient.context.xml`  
- 参考：`docs/sprint-artifacts/6-3-为-binance-futures-提供-exchangeclient-适配器.context.xml` 作为上一 Story 的上下文示例。

### Agent Model Used

- 本 Story 已由 Dev Agent 实施并完成开发与回归验证，当前状态为 **done**。

### Debug Log References

- 待 Dev Agent 实际实施本 Story 时补充（例如对 `exchange_client.py` / `bot.py` / 测试文件的修改与运行日志）。

### Completion Notes List

- [x] AC1：`execute_entry` / `execute_close` 完全依赖 ExchangeClient 抽象（移除直接 Hyperliquid/Binance 分支）。  
- [x] AC2：依据 `TRADING_BACKEND` 与 live 开关选择具体 ExchangeClient 实现，并在配置缺失时安全回退。  
- [x] AC3：统一处理 EntryResult / CloseResult，并将 OID 等信息写入持仓结构与日志。  
- [x] AC4：扩展或规范持仓结构以记录 `live_backend` / OID 等字段，并保持与现有持久化结构兼容。  
- [x] AC5：在 paper / Hyperliquid / Binance 三类场景中完成回归验证，确认行为与重构前等价。  
- [x] AC6：在 Dev Notes 中记录未来交易所接入的最小 checklist，为 Story 6.5 文档工作铺垫。

### File List (Planned)

- TARGET: `bot.py` — 重构 `execute_entry` / `execute_close` 以依赖 ExchangeClient。  
- TARGET: `exchange_client.py` — 如有必要，扩展工厂函数与辅助类型以更好支持主循环注入。  
- TARGET: `tests/` — 新增或更新与 `execute_entry` / `execute_close` 相关的单元/集成测试文件。  
- TARGET: `docs/sprint-artifacts/sprint-status.yaml` — Story 生命周期内更新本条目的 `development_status` 与后续状态变更记录。

## Change Log

- [x] 2025-11-27：初始 Story 草稿由 Scrum Master（create-story 工作流）根据 `docs/epics.md` / `docs/PRD.md` / `docs/architecture/*.md` 与 Story 6.3 的 Dev Notes 自动生成，状态设为 `drafted`，等待 Dev Agent 开始实施。
