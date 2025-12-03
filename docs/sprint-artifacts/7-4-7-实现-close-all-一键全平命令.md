# Story 7.4.7: 实现 /close_all 一键全平命令

Status: Done

## Story

As a user,
I want to close all or directional positions via a confirmed Telegram `/close_all` command,
so that I can quickly exit the market in extreme conditions without logging into the exchange.

## Acceptance Criteria

1. **AC1 – 支持 /close_all 命令基本格式（对齐 Epic 7.4.7 与 PRD FR27）**  
   - 支持以下命令形式：`/close_all`、`/close_all long`、`/close_all short`；  
   - 不带方向参数时，等价于对所有方向（long + short）持仓进行预览；  
   - `long` 仅针对多头方向持仓，`short` 仅针对空头方向持仓，方向标记需与现有持仓结构保持一致。

2. **AC2 – 预览阶段：首次调用不触发真实平仓，仅返回汇总信息**  
   - 当收到不带 `confirm` 的 `/close_all ...` 命令时：  
     - 不下发任何实盘或纸上平仓订单；  
     - 基于**最新持仓快照**筛选出命令范围内的持仓集合（all / long / short）；  
     - 计算：  
       - 将被影响的持仓数量（positions count）；  
       - 总名义金额（USDT），按 long / short 方向分组展示（例如：`long: $X, short: $Y, total: $Z`）；  
     - 返回的 Telegram 消息中：  
       - 用清晰的列表展示各方向的持仓数量与总名义金额；  
       - 明确提示下一步需要输入的确认命令形式，例如：  
         - `/close_all confirm`（全部方向）  
         - `/close_all long confirm`（仅多头）  
         - `/close_all short confirm`（仅空头）。

3. **AC3 – 确认阶段：带 confirm 的命令执行 reduce-only 全平**  
   - 当收到带 `confirm` 的命令（`/close_all confirm`、`/close_all long confirm`、`/close_all short confirm`）时：  
     - 再次获取**最新持仓快照**（不能直接复用预览阶段的旧数据）；  
     - 按命令范围（all / long / short）筛选目标持仓；  
     - 对于每个符合条件的 symbol：  
       - 计算当前名义持仓与方向；  
       - 下发 reduce-only 市价单（或等价实现）执行**全平**；  
       - 收集每个 symbol 的执行结果（成功 / 失败、名义金额、方向、简要错误原因）。  
     - Telegram 返回文案中至少包含：  
       - 成功平仓的 symbol 数量与总名义金额；  
       - 若存在失败的 symbol，标记为“部分失败”，并简要列举若干失败样例及错误类型（详细信息写入日志）。

4. **AC4 – 无可平仓位场景的安全处理**  
   - 在预览阶段：当命令范围内没有任何持仓时：  
     - 返回“当前无可平仓位”的提示信息，并建议用户使用 `/positions` 查看当前持仓；  
     - 不执行任何后续操作。  
   - 在确认阶段：当基于最新持仓快照发现命令范围内仍然没有持仓时：  
     - 不发送任何订单；  
     - 返回“当前无可平仓位，未执行平仓操作”的提示，并说明可能是行情期间已通过其它路径平仓。

5. **AC5 – 错误与部分失败处理（对齐 PRD 风控与日志要求）**  
   - 对于下单过程中的错误（如交易所拒单、网络异常、参数不合法、backend 未就绪等）：  
     - 不影响其它 symbol 的平仓执行（逐 symbol 容错）；  
     - 在日志中为每个失败的 symbol 记录结构化信息：  
       - symbol、方向、名义金额、预期动作（all / long / short）、错误原因摘要；  
     - Telegram 返回文案：  
       - 若全部 symbol 失败，明确提示“全部失败”，并给出下一步建议；  
       - 若部分成功部分失败，明确提示“部分失败”，并列出少量代表性的失败条目及错误类型，其余失败细节以“详见日志”说明。

6. **AC6 – 与 Kill-Switch / 每日亏损限制联动**  
   - 当 Kill-Switch 或每日亏损限制已激活时：  
     - `/close_all` 仍然允许执行，因为它只会减仓或清仓，不会增加新风险敞口；  
     - 不应被 entry 过滤逻辑所拦截；  
     - 推荐在返回文案中附带当前风控状态摘要（例如提示“Kill-Switch 已激活，当前仅允许平仓/减仓操作”）。  
   - 在 Epic 文档推荐的操作顺序中，文案应简要提示：  
     - 极端行情下的标准流程：`/kill` → `/close_all ...`（预览）→ `/close_all ... confirm`（执行）。

7. **AC7 – 单元测试与回归**  
   - 在 `tests/` 目录中为 `/close_all` 命令新增测试用例，至少覆盖：  
     - 仅预览不确认时的行为（all / long / short 三种范围，在有持仓与无持仓两种情况下）；  
     - 确认命令成功全平多 symbol 的场景（包括仅多头 / 仅空头 / 混合持仓）；  
     - 部分失败场景（例如部分 symbol 下单失败），验证 Telegram 文案与日志记录；  
     - Kill-Switch / 日亏限制激活状态下 `/close_all` 仍可执行、且不会被 entry 过滤逻辑阻挡；  
     - 参数非法（未知方向、confirm 位置错误等）时的错误提示与不下单行为。  
   - 运行 `./scripts/run_tests.sh` 时，所有既有测试与本 Story 新增测试均通过。

## Tasks / Subtasks

- [x] **Task 1 – 设计 /close_all 命令接口与参数解析（AC1, AC2 部分）**  
  - [x] 1.1 在现有 Telegram 命令分发层中为 `/close_all` 注册命令入口，遵循与 `/close`、`/kill` 等命令一致的注册模式；  
  - [x] 1.2 实现参数解析逻辑：解析可选方向参数（`long` / `short`）与可选 `confirm` 标记，保证对非法组合（如 `/close_all foo`、`/close_all confirm confirm`）返回清晰错误；  
  - [x] 1.3 与现有持仓结构和 `/positions` 输出保持符号与方向表示方式的一致性（如 long/short 的内部枚举值）。

- [x] **Task 2 – 实现预览阶段逻辑（AC2, AC4 部分）**  
  - [x] 2.1 在执行层或一个新的“批量平仓 orchestrator” 中封装获取当前持仓快照与按方向过滤的逻辑；  
  - [x] 2.2 基于过滤结果计算 long/short/total 的名义金额与持仓数量；  
  - [x] 2.3 在 Telegram 层构造易读的预览文案，包括：各方向持仓数量、名义金额与示例 symbol 列表；  
  - [x] 2.4 当预览范围内无持仓时，返回“无可平仓位”提示，并建议用户使用 `/positions` 命令进一步确认。

- [x] **Task 3 – 实现确认阶段批量全平执行（AC3, AC5 部分）**  
  - [x] 3.1 再次获取最新持仓快照并过滤出目标 symbol 集合，避免使用预览阶段的陈旧数据；  
  - [x] 3.2 为每个目标 symbol 调用统一的“单 symbol 全平”接口（可复用 `/close` 的执行实现），确保使用 reduce-only 市价单或等价机制；  
  - [x] 3.3 聚合所有 symbol 的执行结果形成汇总结构（成功列表 + 失败列表），并据此生成 Telegram 返回文案；  
  - [x] 3.4 为所有失败的 symbol 记录结构化日志，包含 symbol、方向、名义金额、backend 类型与错误原因。

- [x] **Task 4 – 风控集成与测试（AC6, AC7）**  
  - [x] 4.1 确认 `/close_all` 路径在 Kill-Switch / 日亏限制激活状态下不会被 entry 过滤逻辑拦截，仅依赖平仓执行路径；  
  - [x] 4.2 在现有风控与 Telegram 命令测试基础上新增 `/close_all` 相关用例，覆盖正常、部分失败和无持仓等场景；  
  - [x] 4.3 运行 `./scripts/run_tests.sh` 并确保所有测试通过，必要时更新测试快照或期望文案。

## Dev Notes

### Requirements & Context Summary

- 本 Story 属于 **Epic 7.4: Telegram 命令集成（Post-MVP）** 的第七个实现 Story，对应 `sprint-status.yaml` 中的 key：`7-4-7-实现-close-all-一键全平命令`。  
- 需求主要来源：  
  - Epic 风控文档 `docs/epic-risk-control-enhancement.md` 中 **Story 7.4.7: 实现 /close_all 一键全平命令**：  
    - 定义了 `/close_all [long|short|all]` 命令的预览与确认两阶段行为；  
    - 要求第一次调用仅做持仓和名义金额预览，并通过 `confirm` 形式进行二次确认；  
    - 明确要求对部分失败进行标记并写入详细日志。[Source: docs/epic-risk-control-enhancement.md#Story-7.4.7-实现-close_all-一键全平命令]  
  - 风控 PRD 文档 `docs/prd-risk-control-enhancement.md` 中的 **FR27**：  
    - 定义 `/close_all [long|short|all]` 在二次确认前需要展示将被影响的持仓数量与总名义金额预览；  
    - 强调该命令是在极端行情或紧急风险场景下一键撤出风险敞口的重要工具。[Source: docs/prd-risk-control-enhancement.md#Telegram-命令集成]  
  - `docs/epics.md` 中 **Epic 7: 风控系统增强（Emergency Controls）** 与 **Epic 7.4: Telegram 命令集成**：  
    - 将 `/close`、`/close_all`、`/sl`、`/tp`、`/tpsl` 一起建模为远程仓位管理与应急风控能力；  
    - 将 `/close_all` 明确标记为“一键全平命令”，与 Kill-Switch 联动使用。[Source: docs/epics.md#Epic-7.4-Telegram-命令集成-Post-MVP]

### Architecture & Implementation Constraints

- **模块边界与职责（参考 `docs/architecture/06-project-structure-and-mapping.md` 与现有 7.4.x 实现）：**  
  - `notifications/commands/close.py` 及相关命令模块：已经为单 symbol 平仓提供了统一的执行与文案路径，本 Story 应尽量复用而非重复造轮子；  
  - `notifications/telegram_commands.py` / `notifications/commands/base.py`：集中管理命令注册与帮助信息，`/close_all` 需要在此注册并对齐帮助文案；  
  - `core/` + `execution/` + `exchange/` 层：负责实际持仓查询与平仓执行逻辑（含 reduce-only、市价单与最小下单量处理），Telegram 层只做 orchestration 与文案。  
- **错误处理与日志模式（参考 `docs/architecture/07-implementation-patterns.md` 与 `/close` 实现）：**  
  - 不允许因为单个 symbol 平仓失败导致整个 `/close_all` 命令抛异常或中断主循环；  
  - 建议为 `/close_all` 使用统一的 `action` 标识（例如 `TELEGRAM_CLOSE_ALL`），便于在日志与监控中查询；  
  - 对外文案保持简洁，复杂详情通过日志和调试工具查看。

### Project Structure Notes

- 预计主要涉及文件（以实际实现为准）：  
  - `notifications/commands/close_all.py`（可选，新建）或在现有 close 命令模块中扩展批量全平 orchestration；  
  - `notifications/commands/__init__.py` / `notifications/commands/base.py` —— 注册 `/close_all` 命令及帮助信息；  
  - `notifications/telegram_commands.py` —— 导出 `/close_all` 相关 handler，集成到轮询主循环；  
  - `bot.py` —— 如需在命令处理路径中访问最新状态（持仓、权益），可增加轻量的 helper 函数；  
  - `tests/test_telegram_close_all_command.py` 或在现有 Telegram 命令测试文件中新增 `/close_all` 用例。

### Learnings from Previous Stories

- **前置 Story：7.4.1 ～ 7.4.6**  
  - 7.4.1–7.4.5 已经建立起 Telegram 命令接收、风控命令（`/kill`、`/resume`、`/status`、`/reset_daily`）、帮助与安全校验的完整链路；  
  - 7.4.6 `/close` Story 已经解耦出“单 symbol 平仓”的执行与文案模式，并处理了部分平仓、全平、无持仓、错误与风控联动；  
  - 本 Story 应该：  
    - 直接复用 `/close` 的执行与风控集成逻辑，在其之上实现“批量 orchestrator”；  
    - 复用已有的日志与测试模式，保持 7.4.x 命令族的一致性。

### References

- [Source: docs/epic-risk-control-enhancement.md#Story-7.4.7-实现-close_all-一键全平命令]  
- [Source: docs/prd-risk-control-enhancement.md#Telegram-命令集成]  
- [Source: docs/epics.md#Epic-7-风控系统增强-Emergency-Controls]  
- [Source: docs/epics.md#Epic-7.4-Telegram-命令集成-Post-MVP]  
- [Source: docs/sprint-artifacts/7-4-6-实现-close-单品种平仓命令.md]  
- [Source: docs/architecture/06-project-structure-and-mapping.md]  
- [Source: docs/architecture/07-implementation-patterns.md]

## Dev Agent Record

### Context Reference

- 相关 PRD 与 Epic：  
  - `docs/epic-risk-control-enhancement.md#Story-7.4.7-实现-close_all-一键全平命令`  
  - `docs/prd-risk-control-enhancement.md#Telegram-命令集成`  
- 相关已实现 Story：  
  - `docs/sprint-artifacts/7-4-1-实现-telegram-命令接收机制.md`  
  - `docs/sprint-artifacts/7-4-2-实现-kill-和-resume-命令.md`  
  - `docs/sprint-artifacts/7-4-3-实现-status-命令.md`  
  - `docs/sprint-artifacts/7-4-4-实现-reset-daily-命令.md`  
  - `docs/sprint-artifacts/7-4-5-实现-help-命令和安全校验.md`  
  - `docs/sprint-artifacts/7-4-6-实现-close-单品种平仓命令.md`

### Agent Model Used

- Cascade（本 Story 草稿由 SM/AI 协同创建，用于指导后续 Dev Story 实施与代码评审）

### Debug Log References

- 建议在 `/close_all` 命令实现中遵循以下日志模式：  
  - 收到授权 Chat 的 `/close_all` 命令时记录 `INFO` 日志，包含 `direction_scope`（all/long/short）、`with_confirm`、`chat_id` 与解析结果；  
  - 在预览阶段返回“无可平仓位”时记录 `INFO` 或 `WARNING` 日志，标明当前持仓与命令范围；  
  - 在执行阶段对每个 symbol 的平仓结果记录 `INFO`/`WARNING`/`ERROR` 日志，包含 symbol、方向、名义金额与错误原因；  
  - 对异常路径（网络错误、backend 不可用等）记录 `ERROR` 日志，并确保异常不会中断主循环。

### Completion Notes List

- [x] 初始 Story 草稿由 `/create-story` 工作流创建，状态设为 `ready-for-dev`，等待后续 Dev Story 实施与代码评审。
- [x] 2025-12-03: 实现完成，所有 AC 验证通过
  - 创建 `notifications/commands/close_all.py` 实现批量全平命令
  - 支持预览模式（/close_all, /close_all long, /close_all short）
  - 支持确认模式（/close_all confirm, /close_all long confirm, /close_all short confirm）
  - 实现逐 symbol 容错执行，部分失败不影响其他 symbol
  - 与 Kill-Switch / 每日亏损限制正确联动
  - 新增 51 个测试用例，全部通过（993 tests total）

### File List

- `notifications/commands/close_all.py` (NEW) - /close_all 命令核心实现
- `notifications/commands/__init__.py` (MODIFIED) - 导出 handle_close_all_command
- `notifications/commands/base.py` (MODIFIED) - 注册 /close_all 命令帮助文案
- `notifications/commands/handlers.py` (MODIFIED) - 添加 close_all_handler
- `notifications/commands/positions.py` (MODIFIED) - 为 /positions 输出增加 Markdown 转义，与 /close_all 风格对齐
- `tests/test_telegram_close_all_command.py` (NEW) - 51 个测试用例
- `docs/sprint-artifacts/sprint-status.yaml` (MODIFIED) - Story 状态流转

### Change Log

- 2025-12-03: Story 7.4.7 实现完成，状态更新为 Ready for Review
- 2025-12-03: Code Review 修复
  - HIGH #1: 添加 AC6 要求的极端行情推荐流程提示
  - MEDIUM #2: 补充 File List 中遗漏的 positions.py 和 sprint-status.yaml
  - MEDIUM #3: 在日志中增加 scope(all/long/short) 字段，满足 AC5 结构化日志要求
  - LOW #7: 更新 docstring 说明 dry-run 行为
- 2025-12-03: Code Review 通过，所有测试通过（993 tests），状态更新为 Done
