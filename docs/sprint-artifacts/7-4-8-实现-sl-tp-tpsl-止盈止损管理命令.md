# Story 7.4.8: 实现 /sl /tp /tpsl 止盈止损管理命令

Status: done

## Story

As a user,
I want to manage stop loss and take profit for existing positions via Telegram commands `/sl`, `/tp`, and `/tpsl`,
so that I can protect and adjust positions remotely without logging into the exchange.

## Acceptance Criteria

1. **AC1 – 支持 /sl 命令基本格式与语义 (对齐 Epic 7.4.8 与 PRD FR28)**  
   - 支持以下 /sl 命令形式 (单 symbol 维度):  
     - `/sl SYMBOL price VALUE` 使用绝对价格模式;  
     - `/sl SYMBOL pct VALUE` 使用相对*开仓价*百分比模式;  
     - `/sl SYMBOL VALUE` 为简写模式, 当 `VALUE` 以 `%` 结尾时视为百分比模式, 否则视为价格模式。  
   - `SYMBOL` 使用与现有持仓结构和 `/positions` 输出一致的标识 (如 `BTCUSDT`, `ETHUSDT`), 并沿用统一大小写约定。  
   - 百分比模式下使用 `new_price = entry_price * (1 + VALUE / 100)` 计算目标止损价; 当前价 `current_price` 仅用于做方向与合理性校验 (如多仓 SL 仍需低于当前价)。  
   - 参数解析失败 (缺少 SYMBOL、VALUE 非数字且不带 `%`、额外多余参数等) 时, 返回清晰错误提示而不修改任何 TP/SL。

2. **AC2 – 支持 /tp 命令基本格式与语义 (对齐 Epic 7.4.8 与 PRD FR28)**  
   - 支持与 `/sl` 对称的 /tp 命令形式:  
     - `/tp SYMBOL price VALUE`;  
     - `/tp SYMBOL pct VALUE`;  
     - `/tp SYMBOL VALUE` (根据是否以 `%` 结尾区分价格/百分比模式)。  
   - 百分比模式下, 基于开仓价 `entry_price` 计算目标价 (如多仓 TP 一般为 `entry_price * (1 + 正百分比)`), 但仍以当前价 `current_price` 做方向与合理性校验 (多仓 TP 需高于当前价, 空仓 TP 需低于当前价); 具体通过价格合理性校验保证结果不违反方向约束。  
   - 参数非法或模式混乱 (例如含多余 token) 时, 返回清晰错误提示, 不修改任何 TP/SL。

3. **AC3 – 支持 /tpsl 组合命令一次性配置 SL 与 TP (对齐 Epic 7.4.8 与 PRD FR29)**  
   - 支持命令形式: `/tpsl SYMBOL SL_VALUE TP_VALUE`。  
   - 当 `SL_VALUE` 和 `TP_VALUE` 均以 `%` 结尾时, 视为百分比模式, 对多空仓分别按 Epic 中的百分比规则计算目标价格;  
   - 当两者均为不带 `%` 的数值时, 视为绝对价格模式, 直接将其作为目标止损/止盈价;  
   - 若一个参数为价格、一个为百分比 (模式不一致), 当前版本必须返回错误提示, 明确要求用户统一使用价格或统一使用百分比;  
   - 在模式合法时, /tpsl 命令等价于按相同模式依次调用 `/sl` 与 `/tp`, 但需要以原子方式更新内存中的止损/止盈配置 (成功或失败应保持状态一致)。

4. **AC4 – 无持仓场景的安全处理**  
   - 当当前账户在指定 `SYMBOL` 上没有任何有效持仓时:  
     - `/sl`, `/tp`, `/tpsl` 均不修改任何本地状态或下发任何订单;  
     - Telegram 返回提示如 `当前无 SYMBOL 持仓, 无法设置 TP/SL`, 引导用户使用 `/positions` 进一步确认;  
     - 记录一条信息级 (INFO) 或告警级 (WARNING) 日志, 包含命令类型、symbol 与调用来源, 但不视为错误场景。

5. **AC5 – 止损/止盈价格合理性校验**  
   - 系统在计算并准备更新 SL/TP 之前, 必须根据当前仓位方向与价格进行合理性校验:  
     - 对多仓:  
       - 止损价应低于当前价格一定安全距离;  
       - 止盈价应高于当前价格;  
       - 若计算得到的止损价明显高于当前价 (例如高出一个阈值), 或止盈价明显低于当前价, 应拒绝更新并给出错误说明。  
     - 对空仓:  
       - 止损价应高于当前价格;  
       - 止盈价应低于当前价格;  
       - 若计算结果与方向相反, 同样应拒绝更新并返回错误说明。  
   - 对于过于接近市价、可能导致瞬时触发的配置, 可以在文案中给出温和提醒 (例如提示风险), 是否硬拒绝可由实现时权衡。  
   - 校验失败时必须保证不修改任何已有 TP/SL 配置。

6. **AC6 – 状态更新与用户反馈文案**  
   - 命令执行成功并通过所有校验后, 系统需要:  
     - 更新本地持仓结构中与该 symbol 相关的 `stop_loss` 与 `profit_target` 字段 (或等价字段), 确保后续 SL/TP 检查循环能基于新值工作;  
     - Telegram 返回消息中需包含:  
       - 新止损/止盈价格 (或两者), 以及相对当前价格的百分比距离 (如 `-5.00%` / `+8.50%`);  
       - 原有 SL/TP 值 (若存在), 方便用户对比更新前后差异;  
       - 关键信息保持对称性 (多空一致), 文案风格与 `/close`、`/close_all` 命令保持统一。  
   - 在 dry-run 或仅预览模式 (如后续扩展) 下, 任何返回文案必须清晰标记不会真正修改仓位或触发订单。

7. **AC7 – 错误处理与结构化日志 (对齐风控 PRD 与实现模式文档)**  
   - 对于命令执行过程中的错误 (例如无效参数、价格计算异常、状态加载失败等):  
     - 不修改任何现有 SL/TP 配置;  
     - 在日志中记录结构化信息, 至少包括: 命令类型 (`sl` / `tp` / `tpsl`)、symbol、当前价格、目标价格或百分比、方向、多空标记以及错误原因摘要;  
     - 用户侧 Telegram 文案保持简洁友好, 避免暴露内部实现细节, 同时给出下一步建议 (如检查当前持仓或命令格式)。  
   - 错误不会导致 Bot 主循环退出或中断当前迭代, 与现有 `/close`、`/close_all` 命令的错误处理模式保持一致。

8. **AC8 – 单元测试与回归 (对齐测试与回归策略)**  
   - 在 `tests/` 目录中为 `/sl`、`/tp`、`/tpsl` 命令新增测试用例, 至少覆盖:  
     - 有持仓与无持仓下的 /sl, /tp, /tpsl 基本路径;  
     - 百分比模式 (正/负百分比) 与价格模式的行为;  
     - 模式不一致的 /tpsl (价格 + 百分比) 返回错误并不更新状态;  
     - 价格明显不合理导致的拒绝更新;  
     - 与 Kill-Switch / 每日亏损限制联动下, SL/TP 更新仍允许执行 (不被 entry 过滤逻辑阻挡);  
     - 异常与错误路径下的结构化日志与用户提示。  
   - 运行 `./scripts/run_tests.sh` 时, 所有既有测试与本 Story 新增测试均需通过。

## Tasks / Subtasks

- [x] **Task 1 – 设计 /sl /tp /tpsl 命令接口与参数解析 (AC1–AC3)**  
  - [x] 1.1 在现有 Telegram 命令分发层中为 `/sl`, `/tp`, `/tpsl` 注册命令入口, 复用 `/close`、`/close_all` 使用的命令注册与安全校验模式;  
  - [x] 1.2 设计并实现参数解析逻辑, 支持 price / pct / 简写三种模式, 并在解析阶段尽早识别明显非法输入;  
  - [x] 1.3 与 `/positions` 输出保持一致的 symbol 命名与方向约定, 避免由于大小写或后缀差异导致的匹配失败。

- [x] **Task 2 – 价格计算与合理性校验 (AC1–AC5)**  
  - [x] 2.1 基于当前行情价格与持仓方向, 实现 price / pct 两种模式下的目标价格计算函数, 并对多空方向分别处理;  
  - [x] 2.2 实现统一的价格合理性校验函数, 明确多仓与空仓下 SL/TP 的允许区间与异常场景;  
  - [x] 2.3 为后续复用, 将上述计算与校验逻辑封装在独立的 helper 模块或函数中, 避免在多个命令 handler 中重复实现。

- [x] **Task 3 – 状态更新与风控集成 (AC4–AC6)**  
  - [x] 3.1 复用现有持仓快照与状态管理路径 (如用于 `/close` 的逻辑), 安全地读取并更新指定 symbol 的 `stop_loss` 与 `profit_target` 字段;  
  - [x] 3.2 确保 SL/TP 更新不与 Kill-Switch 或每日亏损限制冲突: 在这些风控开关激活时, SL/TP 更新仍被允许执行, 因为它们只影响风控触发点而不增加风险敞口;  
  - [x] 3.3 设计与 `/close`、`/close_all` 一致的 Telegram 返回文案与日志结构, 包括方向、目标价、与当前价的距离、旧值与新值等关键信息。

- [x] **Task 4 – 错误处理与日志 (AC4, AC7)**  
  - [x] 4.1 统一处理无持仓、参数非法、价格异常、状态加载失败等错误场景, 确保不会修改现有状态或中断主循环;  
  - [x] 4.2 在日志中为 TP/SL 命令建立统一的 `action` 标识 (例如 `TELEGRAM_TPSL_UPDATE`), 便于后续审计与调试;  
  - [x] 4.3 对用户返回简明错误提示与下一步建议, 如提示使用 `/positions` 或检查命令格式。

- [x] **Task 5 – 测试与回归 (AC8)**  
  - [x] 5.1 在现有 Telegram 命令测试文件基础上新增 /sl /tp /tpsl 相关测试用例, 覆盖正常、边界与错误场景;  
  - [x] 5.2 在必要时新增专门的测试文件 (如 `tests/test_telegram_tpsl_commands.py`), 避免单个测试文件过于臃肿;  
  - [x] 5.3 运行 `./scripts/run_tests.sh` 并确保新增逻辑不会破坏现有测试, 如有需要更新期望文案或快照。

## Dev Notes

### Requirements & Context Summary

- 本 Story 属于 **Epic 7.4: Telegram 命令集成 (Post-MVP)** 的第八个实现 Story, 对应 `sprint-status.yaml` 中的 key: `7-4-8-实现-sl-tp-tpsl-止盈止损管理命令`。  
- 需求主要来源:  
  - Epic 文档 `docs/epic-risk-control-enhancement.md` 中 **Story 7.4.8: 实现 /sl /tp /tpsl 止盈止损管理命令**:  
    - 明确了 `/sl`, `/tp`, `/tpsl` 三类命令的参数模式 (price / pct / 简写) 与行为约束;  
    - 定义了无持仓时的安全处理、价格合理性校验与错误日志的基本要求。  
  - 风控 PRD 文档 `docs/prd-risk-control-enhancement.md` 中 **FR28 与 FR29**:  
    - FR28: 通过 `/sl SYMBOL ...` 与 `/tp SYMBOL ...` 为单个品种设置或调整止损与止盈, 支持价格与百分比两种模式, 并对明显不合理的价格进行校验与拒绝;  
    - FR29: 通过 `/tpsl SYMBOL SL_VALUE TP_VALUE` 一次性为单个品种配置止损与止盈参数, 要求内部逻辑保证模式一致或给出清晰错误提示。  
  - `docs/epics.md` 中 **FR-OPS3: Telegram 仓位平仓与 TP/SL 远程控制** 与 **Epic 7: 风控系统增强 (Emergency Controls)**:  
    - 将 `/close`, `/close_all`, `/sl`, `/tp`, `/tpsl` 建模为一组远程仓位管理与应急风控能力;  
    - 强调通过 Telegram 在无需登录交易所的情况下完成大部分日常仓位管理与风险控制操作。

### Architecture & Implementation Constraints

- 相关架构约束参考:  
  - `docs/architecture/06-project-structure-and-mapping.md`:  
    - Telegram 通知与命令处理集中在 `notifications/` 层;  
    - 实际的持仓状态与执行逻辑位于 `core/`, `execution/`, `exchange/` 层, Telegram 层不直接触达交易所 SDK。  
  - `docs/architecture/07-implementation-patterns.md`:  
    - Python 代码统一使用 snake_case 命名, 常量使用 UPPER_SNAKE_CASE;  
    - 错误处理遵循「记录日志但不终止主循环」原则;  
    - LLM/Telegram 等外部集成通过专门模块封装, 统一错误与重试策略。  
- 需要与现有 `/close`、`/close_all` 的实现模式保持一致:  
  - 命令解析与分发集中在 `notifications/telegram_commands.py` 与 `notifications/commands/` 子模块;  
  - 核心执行与风控集成通过 `bot.py` + `core/` + `execution/` + `exchange/` 路径完成;  
  - 所有 TP/SL 更新应在本地状态与实际执行路径间保持一致, 避免出现本地状态已更新但风控检查尚未生效的情况。

### Project Structure Notes

- 预计主要涉及文件 (以实际实现为准):  
  - `notifications/telegram_commands.py` — 新增 `/sl`, `/tp`, `/tpsl` 命令 handler 的注册与入口导出;  
  - `notifications/commands/` 子模块 — 建议新增专门的 TP/SL 命令实现模块, 或在现有命令模块中增加 TP/SL 相关逻辑, 统一管理命令级参数解析与文案构造;  
  - `core/state.py` / `core/persistence.py` — 如需读取或更新持仓与 TP/SL 状态, 应通过统一的状态管理接口进行;  
  - `execution/` 与 `exchange/` 模块 — 若需要在实盘路径中对 TP/SL 调整进行实际下单或修改订单, 应通过统一的执行抽象完成 (当前 MVP 可先聚焦本地状态与纸上路径);  
  - `tests/` 目录下与 Telegram 命令相关的测试文件, 如现有的 `/close`、`/close_all` 测试。

### Learnings from Previous Stories

- 前置 Story: 7.4.1 ～ 7.4.7 已经建立起完整的 Telegram 命令接收、风控集成与仓位管理能力:  
  - Story 7.4.1 建立 Telegram 命令接收机制与基础 handler;  
  - Story 7.4.2 实现 `/kill` 与 `/resume`, 定义 Kill-Switch 与 Telegram 的交互模式;  
  - Story 7.4.3 与 7.4.4 提供 `/status` 与 `/reset_daily`, 已经联通风控状态与 Telegram 命令;  
  - Story 7.4.6 `/close` 与 Story 7.4.7 `/close_all` 已经实现单 symbol 平仓与一键全平, 并对无持仓、部分失败、风控联动和测试策略给出完整模式。  
- 对本 Story 的启示:  
  - `/sl` `/tp` `/tpsl` 的 handler 应复用已有命令接收与安全校验通路, 不应重新实现一套 Telegram 验证逻辑;  
  - 价格计算与合理性校验应统一封装, 便于在未来扩展到其它 TP/SL 相关功能;  
  - 日志与审计建议延续 7.4.x 既有模式, 为 TP/SL 命令增加统一的 action 标识与结构化字段 (如 symbol、side、old_sl/tp、新 sl/tp、distance_pct 等)。

### References

- `docs/epic-risk-control-enhancement.md#Story-7.4.8-实现-sl-tp-tpsl-止盈止损管理命令`  
- `docs/prd-risk-control-enhancement.md#Telegram-命令集成` (FR28, FR29)  
- `docs/epics.md#Epic-7-风控系统增强-Emergency-Controls`  
- `docs/epics.md#FR-OPS3-Telegram-仓位平仓与-TP-SL-远程控制`  
- `docs/architecture/06-project-structure-and-mapping.md`  
- `docs/architecture/07-implementation-patterns.md`  
- `docs/sprint-artifacts/7-4-6-实现-close-单品种平仓命令.md`  
- `docs/sprint-artifacts/7-4-7-实现-close-all-一键全平命令.md`

## Dev Agent Record

### Context Reference

- 相关 PRD 与 Epic:  
  - `docs/epic-risk-control-enhancement.md#Story-7.4.8-实现-sl-tp-tpsl-止盈止损管理命令`  
  - `docs/prd-risk-control-enhancement.md#Telegram-命令集成`  
- 相关已实现 Story:  
  - `docs/sprint-artifacts/7-4-1-实现-telegram-命令接收机制.md`  
  - `docs/sprint-artifacts/7-4-2-实现-kill-和-resume-命令.md`  
  - `docs/sprint-artifacts/7-4-3-实现-status-命令.md`  
  - `docs/sprint-artifacts/7-4-4-实现-reset-daily-命令.md`  
  - `docs/sprint-artifacts/7-4-5-实现-help-命令和安全校验.md`  
  - `docs/sprint-artifacts/7-4-6-实现-close-单品种平仓命令.md`  
  - `docs/sprint-artifacts/7-4-7-实现-close-all-一键全平命令.md`

### Agent Model Used

- Cascade (本 Story 草稿由 /create-story 工作流在 AI 协助下生成, 供后续 Dev Story 实施与代码评审使用)

### Debug Log References

- 建议在 `/sl`, `/tp`, `/tpsl` 命令实现中遵循以下日志模式:  
  - 收到授权 Chat 的 TP/SL 命令时记录 INFO 日志, 包含命令类型、symbol、原 SL/TP、目标 SL/TP、百分比距离与解析结果;  
  - 在无持仓、参数非法或价格不合理等场景下记录 WARNING 日志, 并在用户文案中给出清晰提示与下一步建议;  
  - 在成功更新 SL/TP 时记录 INFO 日志, 包含方向、旧值、新值、distance_pct 等字段, 便于回溯;  
  - 在异常路径 (如状态加载失败、内部异常) 下记录 ERROR 日志, 同时确保异常不会中断主循环。

### Completion Notes List

- [x] 初始 Story 草稿由 `/create-story` 工作流创建, 状态设为 `ready-for-dev`, 等待后续 Dev Story 实施与代码评审。
- [x] 实现完成，所有 AC 验证通过，1080 个测试全部通过。

### File List

- **NEW** `notifications/commands/tpsl.py` — `/sl`, `/tp`, `/tpsl` 命令处理模块，包含参数解析、价格计算、合理性校验、状态更新逻辑。
- **MODIFIED** `notifications/commands/__init__.py` — 导出 `handle_sl_command`, `handle_tp_command`, `handle_tpsl_command`, `get_positions_for_tpsl`, `TPSLParseResult`, `TPSLUpdateResult`, `PriceMode`。
- **MODIFIED** `notifications/commands/handlers.py` — 添加 `sl_handler`, `tp_handler`, `tpsl_handler` 并注册到命令处理器，添加 `update_tpsl_fn` 和 `get_current_price_fn` 参数。
- **MODIFIED** `notifications/commands/base.py` — 在 `COMMAND_REGISTRY` 中添加 `/sl`, `/tp`, `/tpsl` 命令帮助信息。
- **MODIFIED** `bot.py` — 添加 `update_telegram_tpsl` 和 `get_current_price_for_coin` 函数，并在 `create_kill_resume_handlers` 调用中注入。
- **NEW** `tests/test_telegram_tpsl_commands.py` — 87 个测试用例覆盖所有 AC 场景及集成测试。

### Change Log

- 2024-12-03: 实现 `/sl`, `/tp`, `/tpsl` 命令，支持价格模式、百分比模式和简写模式，包含完整的价格合理性校验、错误处理和风控集成。
- 2024-12-03: [Code Review Fix] 完成状态更新集成，添加 `update_telegram_tpsl` 和 `get_current_price_for_coin` 函数，修复百分比模式与当前价校验逻辑: 以开仓价为百分比基准计算目标价, 以当前价做方向/距离合理性校验。
