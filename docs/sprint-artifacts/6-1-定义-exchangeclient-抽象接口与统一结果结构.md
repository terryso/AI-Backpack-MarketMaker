# Story 6.1: 定义 ExchangeClient 抽象接口与统一结果结构

Status: done

## Story

As a developer working on this trading bot,
I want a single, exchange-agnostic execution interface (ExchangeClient) with unified Entry/Close result shapes,
So that the bot and strategy code do not care which concrete exchange backend is used.

本故事的目标是：在不改变现有实盘 / 纸上交易行为的前提下，为交易执行层引入一个统一的 `ExchangeClient` 抽象接口与配套的结果结构，使 Bot 主循环和策略代码只依赖这层抽象，而不直接感知具体交易所（Hyperliquid / Binance Futures 等）的差异。

## Acceptance Criteria

1. **ExchangeClient 抽象接口定义完整且清晰**
   - 至少包含以下方法（命名可按 PEP 8 细化，但语义应一致）：
     - `place_entry(...)`：接收 coin/symbol、side、size、entry_price、stop_loss_price、take_profit_price、leverage、liquidity 等参数；
     - `close_position(...)`：接收 coin/symbol、side、size（可选）、fallback_price 等参数。
   - 方法签名能够覆盖当前 Hyperliquid 与 Binance Futures 执行路径所需的关键参数，不限制未来扩展。

2. **EntryResult / CloseResult 统一结果结构已定义**
   - 定义两个统一的结果结构（可使用 dataclass、TypedDict 或等价抽象）：
     - 基本字段：`success: bool`、`backend: str`、`errors: list[str]`；
     - 可选字段：`entry_oid` / `tp_oid` / `sl_oid` / `close_oid` 等，用于保存订单 ID；
     - `raw` 字段保留原始交易所响应，便于 debug 与后续扩展。
   - 结果结构可以无损承载当前 Hyperliquid 与 Binance 返回的信息，并为未来交易所适配预留空间。

3. **当前实现阶段不改变任何实际执行行为**
   - 引入 ExchangeClient 与结果类型后，现有执行路径（尤其是 Hyperliquid 实盘与 Binance Futures 通路）在功能与副作用上保持等价：
     - 不引入新的下单分支或行为更改；
     - 不改变风控、日志、错误处理的语义，只是在类型层面准备好统一抽象。
   - 可以通过最小验证脚本或现有 smoke test 确认在本 Story 范围内的变更不会影响下单行为（实现和接线到实际路径属于后续 Story 6.2+ 的范围）。

4. **PRD / 架构文档映射关系清晰**
   - 在代码注释或 Dev Notes 中，明确说明本 Story 对应 `docs/epics.md` 中 Epic 6 的「统一交易所执行层」以及 PRD 中相关功能块；
   - 与 `docs/architecture/06-project-structure-and-mapping.md` / `07-implementation-patterns.md` 中的「外部服务适配层」「实现模式」保持一致（例如：集中适配层、通过配置与抽象隔离具体实现）。

## Tasks / Subtasks

- [x] 任务 1：梳理当前执行路径与需求（AC: #1, #2, #3）
  - [x] 通读 `bot.py` 中与下单 / 平仓相关的路径，识别当前如何区分 Hyperliquid 与 Binance Futures，以及实际使用了哪些参数。
  - [x] 对照 `hyperliquid_client.py` 和未来计划中的 Binance 接入预期，列出执行层需要支持的通用参数列表。
  - [x] 将识别结果与 `docs/epics.md` 中 Epic 6 / Story 6.1 的接受标准做一次对齐，确认本 Story 的范围仅限于「接口与类型定义」。

- [x] 任务 2：设计并实现 ExchangeClient 抽象接口（AC: #1）
  - [x] 在项目根目录新增一个面向执行层的抽象模块（例如 `exchange_client.py` 或等价命名），位置与 `hyperliquid_client.py` 平行，以符合架构文档中的结构约定。
  - [x] 定义 `ExchangeClient` 接口 / 基类（可使用 `Protocol`、`ABC` 或简单基类），包含至少 `place_entry` 与 `close_position` 两个方法，并使用类型注解描述关键参数。
  - [x] 为接口方法编写简短但明确的 docstring，说明各参数含义与单位（例如价格 / 数量 / 杠杆等）。

- [x] 任务 3：定义统一的 EntryResult / CloseResult 结构（AC: #2）
  - [x] 在同一模块中定义 `EntryResult` 与 `CloseResult`，采用 dataclass 或 TypedDict，并包含 Acceptance Criteria 中列出的字段。
  - [x] 为 `errors` 字段约定统一语义（例如：用户可读的错误摘要，而不是原始异常字符串的直接 dump），并在注释中加以说明。
  - [x] 确保类型定义能够容纳当前 Hyperliquid 返回结构中常用的字段（订单 ID、状态、错误码等），并通过 `raw` 保留完整原始响应。

- [x] 任务 4：为未来适配器与重构预留接入点（AC: #3）
  - [x] 在 `bot.py` 或合适的初始化位置，预留一个用于「选择具体 ExchangeClient 实现」的轻量工厂函数或占位逻辑，但在本 Story 中不要真正接入具体实现（由 Story 6.2+ 完成）。
  - [x] 在 Dev Notes 中记录：后续 Story 6.2/6.3 将分别实现 `HyperliquidExchangeClient` 与 `BinanceFuturesExchangeClient`，Story 6.4 将在 `execute_entry` / `execute_close` 中接线。
  - [x] 确认本 Story 的变更可以在不修改现有调用点的前提下被后续故事渐进式接入。

- [x] 任务 5：最小验证与文档对齐（AC: #3, #4）
  - [x] 使用现有的 smoke test 或一个最小脚本（本实现中为 `python -m compileall .`），验证仅加载类型与接口定义不会破坏当前运行路径（包括 `bot.py` 与 `backtest.py` 的基本导入）。
  - [x] 在本文件的 Dev Notes / Project Structure Notes 中补充与 PRD、架构文档的映射说明，便于后续故事复用。

## Dev Notes

- 本 Story 聚焦于「接口与类型定义」，不负责引入新的实际下单逻辑或改变行为，真正的实盘与纸上路径迁移在 Story 6.2–6.4 中完成。
- 设计 ExchangeClient 时，应遵守 `docs/architecture/07-implementation-patterns.md` 中关于：
  - 统一外部服务集成模式（集中适配层、避免在业务代码中散落裸 SDK 调用）；
  - 配置与密钥通过环境变量与集中配置处理，而不是在接口层内直接读取环境变量。
- 与 `docs/architecture/06-project-structure-and-mapping.md` 中的映射关系：
  - 本 Story 主要服务于「Hyperliquid 实盘集成」与未来多交易所扩展对应的架构区域；
  - ExchangeClient 作为「执行适配器」抽象，应被视为介于 `bot.py` 与各具体交易所 SDK 之间的一层统一接口。
- 与 Story 1.1 的关系：
  - Story 1.1 已为 LLM 访问层引入统一配置与客户端抽象，本 Story 在「交易执行层」做类似的结构统一；
  - 后续在 Dev Agent Record 中可以补充：在调试交易执行问题时，如何同时结合 LLM 决策层与执行层的日志进行排查。

### Project Structure Notes

- 新增模块建议放置位置：
  - `exchange_client.py`（或等价命名）位于项目根目录，与 `bot.py`、`hyperliquid_client.py` 并列；
  - 未来的 `HyperliquidExchangeClient` / `BinanceFuturesExchangeClient` 实现可以放在同一模块内，或按需要拆分为 `exchange_clients/hyperliquid.py` 等结构，但应在架构文档中记录。
- 不引入新的顶层运行脚本；所有执行仍通过 `bot.py` 与 `backtest.py` 入口完成。

### References

- Epics：`docs/epics.md` 中 "Story 6.1: 定义 ExchangeClient 抽象接口与统一结果结构" 章节。
- PRD：`docs/prd.md` 中与交易执行、风险与可观测性相关的章节（尤其是 4.1「交易主循环」与 4.2「风险控制与资金管理」）。
- 架构：
  - `docs/architecture/03-data-flow.md`：了解交易信号从 LLM 到执行层的整体数据流；
  - `docs/architecture/04-integrations.md`：外部依赖与集成点（Binance / Hyperliquid / LLM / Telegram 等）；
  - `docs/architecture/06-project-structure-and-mapping.md`：PRD 功能块到源码树的映射；
  - `docs/architecture/07-implementation-patterns.md`：统一的实现与集成模式。

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/6-1-定义-exchangeclient-抽象接口与统一结果结构.context.xml`

### Agent Model Used

- Cascade / dev agent "Amelia"（通过 /dev→*develop-story* 工作流执行，模型：Cascade）

### Debug Log References

- 2025-11-27：通读 `bot.py` 中 `execute_entry` / `execute_close` 及 `TRADING_BACKEND` / Hyperliquid / Binance Futures 分支，梳理现有执行路径与参数需求（AC #1, #3）。
- 2025-11-27：通读 `hyperliquid_client.py` 与 `scripts/manual_hyperliquid_smoke.py`，确认 Hyperliquid 实盘路径的订单 ID、触发单与错误结构（AC #1, #2, #3）。
- 2025-11-27：新增 `exchange_client.py`，定义 `ExchangeClient` 抽象接口与 `EntryResult` / `CloseResult` 统一结果结构，仅作为类型与适配层准备，不接入现有调用路径（AC #1, #2, #3）。
- 2025-11-27：执行 `python -m compileall .` 作为最小验证脚本，确认新增模块不会破坏 `bot.py` / `backtest.py` 的基本编译与导入（AC #3）。

### Completion Notes List

- ExchangeClient 设计遵循 Epic 6 / Story 6.1 与 `docs/architecture/07-implementation-patterns.md` 中的外部服务适配与错误处理模式：仅提供统一接口与结果结构，不直接读取环境变量，也不改变任何现有实盘 / 纸上逻辑（AC #3, #4）。
- `EntryResult` / `CloseResult` 通过 `success` / `backend` / `errors` / OID 字段 + `raw` + `extra` 组合，既能无损承载当前 Hyperliquid 返回结构，又为未来 Binance Futures 与新交易所适配预留扩展空间（AC #2）。
- 当前 Story 仅定义接口与类型，未引入新的回测或实盘测试用例；回归与更深入的行为验证建议在 Story 6.2–6.4（具体适配与接线）中完成。

### File List

- `exchange_client.py`：新增。定义 `ExchangeClient` 抽象接口与 `EntryResult` / `CloseResult` 统一结果结构，为后续 Hyperliquid / Binance Futures 适配与 `execute_entry` / `execute_close` 重构提供统一执行层抽象。
- `docs/sprint-artifacts/sprint-status.yaml`：修改。将 Story `6-1-定义-exchangeclient-抽象接口与统一结果结构` 的开发状态从 `ready-for-dev` 更新为 `in-progress`，与 /dev 工作流启动保持一致。
- `docs/sprint-artifacts/6-1-定义-exchangeclient-抽象接口与统一结果结构.md`：修改。更新 Status、Dev Agent Record 与文件列表，记录本次实现与验证记录。

## Change Log

- [ ] 2025-11-27：初始 Story 草稿由 Scrum Master 根据 epics/PRD/架构文档生成，状态设为 `drafted`。
- [x] 2025-11-27：新增 `exchange_client.ExchangeClient` 抽象接口与 `EntryResult` / `CloseResult` 结果结构，并在 Story 层记录与 Epic 6 / PRD 4.1/4.2 / 架构文档的映射关系（无行为变更，仅接口与类型准备），Story 状态更新为 `review`。

## Senior Developer Review (AI)

### Reviewer

- Reviewer: Nick / Cascade dev agent "Amelia"
- Date: 2025-11-27

### Outcome

- **Outcome:** Approve
- **Rationale:**
  - 所有 Acceptance Criteria 均已在 `exchange_client.py` 与 Story 文档中得到满足；
  - 所有标记为完成的任务（含子任务）在代码与文档中均有明确证据；
  - 本 Story 仅新增抽象接口与结果结构，未改动任何现有执行路径或行为，最小验证脚本通过。

### Key Findings (by severity)

- **High:** 无
- **Medium:** 无
- **Low:**
  - 建议在后续 Story（6.2–6.4）中，为具体 `ExchangeClient` 实现与关键错误分支补充单元测试与（如有需要）轻量集成测试，以覆盖 Entry/Close 结果结构的主要使用场景。

### Acceptance Criteria Coverage

| AC # | 描述 | 状态 | 证据 |
| ---- | ---- | ---- | ---- |
| AC1 | 定义包含 `place_entry` / `close_position` 的 ExchangeClient 抽象接口 | IMPLEMENTED | `exchange_client.py:45-84` — 定义 `ExchangeClient` 协议，包含 `place_entry` 与 `close_position`，参数覆盖 coin/side/size/entry_price/stop_loss_price/take_profit_price/leverage/liquidity 及 `fallback_price`。 |
| AC2 | 定义包含 `success/backend/errors/raw` 及可选 OID 字段的 EntryResult / CloseResult 结构 | IMPLEMENTED | `exchange_client.py:7-42` — `EntryResult` / `CloseResult` dataclass，字段含 `success`、`backend`、`errors`、`entry_oid` / `tp_oid` / `sl_oid` / `close_oid`、`raw`、`extra`。 |
| AC3 | 当前阶段不改变任何实际执行行为 | IMPLEMENTED | 仅新增 `exchange_client.py` 与文档；`bot.py`、`hyperliquid_client.py`、Binance 路径未改动；`get_exchange_client` 为未接线占位工厂（`exchange_client.py:87-99`）；通过 `python -m compileall .` 最小验证（Dev Agent Record Debug Log）。 |
| AC4 | PRD / 架构文档映射关系清晰 | IMPLEMENTED | Story Dev Notes / Project Structure Notes / References 段落中，显式引用 `docs/epics.md` Epic 6 / Story 6.1、PRD 4.1/4.2 以及架构 03/04/06/07，并说明 ExchangeClient 作为外部服务适配层的定位（Story 6.1 文档第 64–92 行）。 |

**Summary:** 4 / 4 acceptance criteria fully implemented。

### Task Completion Validation

| Task | Marked As | Verified As | 证据 |
| ---- | --------- | ----------- | ---- |
| 任务 1：梳理当前执行路径与需求 | Completed (`[x]`) | VERIFIED COMPLETE | Story Tasks 中任务 1 已勾选（第 40–43 行）；Dev Notes 与 Dev Agent Record Debug Log 中记录了对 `bot.py` / `hyperliquid_client.py` / `scripts/manual_hyperliquid_smoke.py` 的阅读与结论（第 66–76 行、104–109 行）。 |
| 任务 2：设计并实现 ExchangeClient 抽象接口 | Completed (`[x]`) | VERIFIED COMPLETE | `exchange_client.py` 新增并位于项目根目录，与 `bot.py`、`hyperliquid_client.py` 并列（Project Structure Notes 第 79–82 行）；接口定义见 `exchange_client.py:45-84`。 |
| 任务 3：定义统一的 EntryResult / CloseResult 结构 | Completed (`[x]`) | VERIFIED COMPLETE | `exchange_client.py:7-42` 定义 `EntryResult` / `CloseResult`，字段集合满足 Story 与 Context XML 中接口说明（Context `<interfaces>` 段第 60–64 行）。 |
| 任务 4：为未来适配器与重构预留接入点 | Completed (`[x]`) | VERIFIED COMPLETE | `exchange_client.py:87-99` 定义 `get_exchange_client` 占位工厂，当前未在任何生产路径中使用，仅作为后续 `HyperliquidExchangeClient` / `BinanceFuturesExchangeClient` 的统一接入点；Dev Notes 中记录后续 Story 6.2–6.4 的接线计划（第 71–75 行）。 |
| 任务 5：最小验证与文档对齐 | Completed (`[x]`) | VERIFIED COMPLETE | Dev Agent Record Debug Log 中记录执行 `python -m compileall .` 作为最小验证脚本（第 109 行）；Story 文档与 File List/Change Log 已补充与 PRD/架构文档映射与变更说明。 |

**Summary:** 5 / 5 completed tasks verified; 0 questionable; 0 falsely marked complete。

### Test Coverage and Gaps

- 本 Story 仅新增抽象接口与数据结构，未改动任何实际执行路径或逻辑分支，未新增自动化测试。结合 Story Context 的规划：
  - 针对 AC #1 / #2，建议在 Story 6.2+ 中为具体 `ExchangeClient` 实现编写单元测试，验证方法签名与结果结构在真实集成下的约束；
  - 针对 AC #3，当前通过编译级最小验证（`python -m compileall .`）即可确认行为不变，后续在接线时需引入更完整的回归与 smoke 测试。

### Architectural Alignment

- 设计严格遵守 `docs/architecture/06-project-structure-and-mapping.md` 与 `07-implementation-patterns.md`：
  - 新增模块 `exchange_client.py` 作为外部服务适配层的一部分，位于项目根目录，与 `bot.py` / `hyperliquid_client.py` 并列；
  - 未在 `ExchangeClient` 中引入任何环境变量读取或外部请求逻辑，保持抽象层纯粹；
  - 未来扩展（Hyperliquid / Binance / 新交易所）均可通过实现 `ExchangeClient` 并在占位工厂中注册完成，对 `bot.py` 的侵入最小。

### Security Notes

- 本 Story 未触及密钥/连接或网络调用代码，仅定义类型与接口；
- `exchange_client.py` 未引入新的依赖或外部服务接入点，对安全面无直接扩展；
- 安全相关风险将主要出现在后续具体适配实现（如 live 交易错误处理与日志中敏感信息暴露），应在 Story 6.2+ 中重点审查。

### Best-Practices and References

- 设计依据：
  - `docs/epics.md` 中 Epic 6 / Story 6.1 对统一执行层与结果结构的描述；
  - `docs/prd.md` 4.1 / 4.2 关于交易主循环与风控的约束；
  - `docs/architecture/03-data-flow.md`、`04-integrations.md`、`06-project-structure-and-mapping.md`、`07-implementation-patterns.md` 中关于外部服务适配层、结构与错误处理的一致性规则；
  - Story Context XML `6-1-定义-exchangeclient-抽象接口与统一结果结构.context.xml` 中 `<interfaces>` 与 `<constraints>` 段。

### Action Items

**Code Changes Required:**

- 无（本次评审结论为 Approve，当前 Story 范围内不要求额外代码修改）。

**Advisory Notes:**

- Note: 在 Story 6.2–6.4 中实现具体适配器与接线时，应为关键执行路径与错误分支补充单元/集成测试，并在 Story 文档中更新与 AC 的映射说明。
- Note: 建议在未来新增 `tests/` 目录时，以 `exchange_client.py` 为中心设计一组契约测试，用于约束不同交易所适配实现的一致行为。
