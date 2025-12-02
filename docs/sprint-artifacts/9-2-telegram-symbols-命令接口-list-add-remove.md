# Story 9.2: Telegram `/symbols` 命令接口（list/add/remove）

Status: done

## Story

As an operator of the trading bot,
I want a `/symbols` command with list/add/remove subcommands,
So that I can inspect and adjust the Paper/Live trading universe via Telegram.

作为负责运行与监控交易 Bot 的运营人员，
我希望在 Telegram 中通过 `/symbols` 命令（支持 list/add/remove 子命令）管理 Paper / Live 模式下的交易 Universe，
从而可以方便地查看当前交易标的，并按需增加或移除交易对，而无需改代码或重启进程。

## Acceptance Criteria

1. **`/symbols list` 展示当前 Universe（AC from epics.md）**  
   - Given Bot 已配置 Telegram Bot Token 与 Chat ID，并正常运行  
   - When 在授权聊天中发送命令：`/symbols list`  
   - Then Bot 返回当前 Paper / Live 交易 Universe 中的所有 symbol，按字母序或稳定顺序展示，
     且输出格式清晰、适合聊天窗口阅读（例如每行一个 symbol，或分组展示）。

2. **`/symbols add <SYMBOL>` 仅管理员可执行 & 成功路径（AC from epics.md，依赖 Story 9.3 校验）**  
   - Given 已通过 `TELEGRAM_ADMIN_USER_ID` 配置管理员用户 ID，且当前聊天消息的 `user_id` 为该管理员  
   - And 已存在可配置 Universe 抽象（Story 9.1，`config/universe.py` 提供 `set_symbol_universe` 与 `get_effective_symbol_universe`）  
   - And 已实现 Story 9.3 中基于 `MARKET_DATA_BACKEND` 的 symbol 有效性校验函数（例如 `validate_symbol_for_universe(symbol: str) -> (bool, str)`，本 Story 仅依赖其接口语义）  
   - When 管理员在授权聊天中发送命令：`/symbols add BTCUSDT`  
   - Then 该命令处理流程：  
     - 解析命令为 `command="symbols"`，子命令 `"add"`，参数 `"BTCUSDT"`；  
     - 调用校验逻辑确认在当前 `MARKET_DATA_BACKEND` 下 symbol 合法；  
     - 在不破坏现有 Universe 行为前提下，将 `BTCUSDT` 合并进运行时 Universe（使用 `set_symbol_universe`，保持去重与大小写归一）；  
     - 返回成功消息，明确指出新增的 symbol 以及当前 Universe 摘要（例如新增前/后的 Universe 差异或总数）。

3. **`/symbols add <SYMBOL>` 非管理员 & 校验失败路径（AC from epics.md + 安全约束）**  
   - Given Telegram 管理员机制已按 Story 8.3 工作（`config.settings.get_telegram_admin_user_id`）  
   - When 非管理员用户尝试发送：`/symbols add BTCUSDT`  
   - Then Bot 返回「无权限修改，只能查看」风格的错误信息，并建议使用 `/symbols list` 等只读命令；  
   - And 不会调用 Universe 修改逻辑，也不会写入任何审计记录以外的日志。  
   - When 管理员用户发送 `/symbols add INVALID`，而 Story 9.3 校验返回「该 symbol 在当前 `MARKET_DATA_BACKEND` 下不被支持」  
   - Then Bot 返回错误提示，内容包括：当前 backend 类型（如 `binance` / `backpack`）、失败原因（如「symbol 不存在」或「计价币种不匹配」），并且不修改 Universe。

4. **`/symbols remove <SYMBOL>` 仅管理员可执行，且不会强制平仓（AC from epics.md）**  
   - Given Universe 中当前包含若干 symbol，且部分 symbol 可能已有持仓  
   - When 管理员发送：`/symbols remove SOLUSDT`  
   - Then：  
     - 若 `SOLUSDT` 在当前 Universe 中：  
       - 从 Universe 覆盖集合中移除该 symbol（通过重建覆盖列表并调用 `set_symbol_universe`）；  
       - 返回成功消息，明确说明「后续不会再为该 symbol 生成新开仓信号」，但**不会**触发任何强制平仓逻辑；  
       - 对现有持仓，仅依赖既有 SL/TP 与风控逻辑管理。  
     - 若 `SOLUSDT` 不在当前 Universe 中：  
       - 返回温和提示（例如「symbol 不在当前 Universe 中，无需移除」），不视为错误。  
   - And 不论成功或无操作，均遵循 Story 9.4 的日志约定：至少记录时间戳、user_id、操作类型（add/remove）、symbol、新旧 Universe 摘要。

5. **非范围与 Backtest 行为保持不变**  
   - Given 使用 `backtest.py` 并通过 `BACKTEST_SYMBOLS` 等机制指定回测 symbol  
   - When 运行回测或查看回测相关日志  
   - Then `/symbols` 命令及运行时 Universe 修改不会影响 Backtest 的 symbol 选择路径，
     Backtest 仍由命令行参数 / env 控制；任何 Universe 相关更改只影响 Paper / Live 模式，符合 Epic 9 范围定义。

6. **最小测试覆盖与安全回归**  
   - Given 运行 `./scripts/run_tests.sh`  
   - When 为 `/symbols` 命令实现新增测试（建议新建 `tests/test_telegram_symbols_commands.py`，
     或在现有 Telegram 测试模块中新增 `TestSymbolsCommand...` 小节）  
   - Then 至少覆盖：  
     - `/symbols list` 基本行为（空 Universe / 默认 Universe / override 后 Universe）；  
     - `/symbols add` 成功路径、非管理员拒绝路径、symbol 无效路径；  
     - `/symbols remove` 成功移除、移除不存在 symbol 的无操作路径；  
     - 对 Universe 抽象的集成（通过 `config.universe` API 验证修改确实生效）。

## Tasks / Subtasks

- [x] **Task 1：命令解析与入口设计**  
  - [x] 在 `notifications/telegram_commands.py` 中，为 `/symbols` 命令设计专用 handler 函数（例如 `handle_symbols_command` 或拆分为 `handle_symbols_list_command` / `handle_symbols_add_command` / `handle_symbols_remove_command`）：  
    - 输入类型沿用现有 `handle_*_command` 签名（`cmd: TelegramCommand, ...`）；  
    - 输出使用已有 `CommandResult` dataclass，便于统一处理与测试。  
  - [x] 在命令分发层（调用 `process_telegram_commands` 的地方）中，将 `/symbols` 命令注册进 `command_handlers` 映射：  
    - 对应 key 为 `"symbols"`（与 `TelegramCommand.command` 的解析结果一致）；  
    - 确保未知命令仍走已有 `handle_unknown_command` 逻辑，不互相干扰。

- [x] **Task 2：`/symbols list` 子命令实现**  
  - [x] 通过 `config.universe.get_effective_symbol_universe()` 读取当前 Universe：  
    - 该函数已经考虑了 runtime override 及默认 `SYMBOLS` 的语义（参见 Story 9.1 实现与 `tests/test_universe.py`）。  
  - [x] 将 symbol 列表格式化为适合 Telegram Markdown 的字符串：  
    - 注意复用或参考 `notifications/telegram.py` 中的 Markdown 转义与消息构建模式（例如 `escape_markdown` / `_escape_markdown`）；  
    - 对于空 Universe，返回明确提示（例如「当前 Universe 为空，系统不会开启任何新交易」），以防止误解为出错。  
  - [x] 返回 `CommandResult(success=True, state_changed=False, action="SYMBOLS_LIST", message=...)`,
    保持与其他命令风格一致。

- [x] **Task 3：`/symbols add` 子命令实现（集成校验与管理员权限）**  
  - [x] 设计内部辅助函数，例如：  
    - `_check_symbols_admin_permission(cmd: TelegramCommand) -> tuple[bool, str]`：基于 `config.settings.get_telegram_admin_user_id()` 判断是否管理员；  
    - `_load_current_universe() / _save_universe(new_symbols: list[str])`：封装对 `config.universe` API 的读写，确保大小写归一与去重。  
  - [x] 在 handler 中实现以下逻辑：  
    - 检查是否提供了 `<SYMBOL>` 参数；若缺失，返回带用法示例的错误消息；  
    - 调用权限检查：非管理员直接返回 permission denied 消息，并建议使用 `/symbols list`；  
    - 对 symbol 做基本规范化（去空格、大写化，如 `btcUSDT` -> `BTCUSDT`）；  
    - 调用 Story 9.3 提供的 symbol 校验接口（当前 Story 只依赖接口语义，不在此实现具体校验逻辑）；  
    - 在校验通过时，合并 symbol 并通过 `set_symbol_universe` 写回；  
    - 构造响应文案：包含旧 Universe 摘要、新 Universe 摘要（例如数量或部分列表），方便在聊天中审阅。  
  - [x] 为成功与失败路径添加 INFO/WARNING 日志，日志内容参考 Story 9.4 的约定：记录 `timestamp`、`user_id`、`symbol`、操作类型等。

- [x] **Task 4：`/symbols remove` 子命令实现（不触发强制平仓）**  
  - [x] Handler 实现要点：  
    - 与 `/symbols add` 共用管理员权限检查逻辑；  
    - 读取当前 Universe，若 symbol 不在其中，则返回「无需操作」提示；  
    - 若在其中，则构造移除后的 Universe 列表，并调用 `set_symbol_universe`；  
    - 响应文案中**必须**明确说明：删除 symbol 仅阻止后续新开仓，不会自动关闭已有持仓。  
  - [x] 日志记录：  
    - 成功移除时，使用 WARNING 或 INFO 级别记录变更（包含旧/新 Universe 摘要）；  
    - 无操作时使用 INFO 级别记录（避免日志噪音过大）。

- [x] **Task 5：测试与文档补充**  
  - [x] 新建 `tests/test_telegram_symbols_commands.py` 或在现有 Telegram 测试文件中新增 `TestSymbolsCommand...` 类：  
    - 利用 `TelegramCommand` 与 `CommandResult` 进行单元测试，无需真实调用 Telegram API；  
    - 使用 `config.runtime_overrides` 与 `config.universe` 提供的 API 控制测试环境；  
    - 覆盖 list/add/remove 的典型与边界场景。  
  - [x] 在必要时更新 `docs/epics.md` 或衍生文档，补充对于 `/symbols` 命令的使用说明与限制，
    但本 Story 不要求对主 PRD 做大规模改写。

## Dev Notes

- **现有相关能力与依赖**  
  - Telegram 命令接收与解析：  
    - 模块：`notifications/telegram_commands.py`  
    - 已实现命令：`/kill`、`/resume`、`/status`、`/balance`、`/risk`、`/reset_daily`、`/config`、`/help` 等。  
    - `TelegramCommandHandler` 负责从 Telegram API 轮询消息并解析为 `TelegramCommand` 对象，
      其中 `command` 字段为无 `/` 前缀的小写命令名。  
  - 配置与管理员权限：  
    - 模块：`config/settings.py`  
    - 管理员用户：`TELEGRAM_ADMIN_USER_ID` 环境变量 + `get_telegram_admin_user_id()` 辅助函数，
      已在 Story 8.3 的测试中覆盖；  
    - 运行时配置覆盖层：`config.runtime_overrides`，已被 `/config` 命令复用。  
  - 可配置 Universe 抽象（Story 9.1 已完成）：  
    - 模块：`config/universe.py`  
    - 核心 API：  
      - `set_symbol_universe(symbols: list[str]) -> None`：设置运行时 Universe 覆盖；  
      - `clear_symbol_universe_override() -> None`：恢复默认 Universe（基于 `config.settings.SYMBOLS`）；  
      - `get_effective_symbol_universe() -> list[str]`：返回当前生效的 symbol Universe；  
      - `get_effective_coin_universe() -> list[str]`：基于 `SYMBOL_TO_COIN` 映射计算 coin Universe。  
    - 设计约束（已在 Story 9.1 文档中说明）：子集过滤、内存存储、线程安全假设、空 Universe 意味着不再开新仓等。

- **实现 `/symbols` 时的关键约束与决策建议**  
  - **权限模型复用**：  
    - `/symbols list` 应对所有用户开放（只读视图），类似 `/config list` / `/config get`；  
    - `/symbols add` / `/symbols remove` 应严格依赖管理员机制，与 `/config set` 的权限语义保持一致。  
  - **校验职责边界**：  
    - symbol 合法性校验是 Story 9.3 的核心职责，本 Story 只应依赖一个清晰的、可替换的校验接口；  
    - 在实际实现中，可以先提供临时占位实现（例如总是返回 True），再由 Story 9.3 替换为真实校验逻辑，
      但 Story 9.2 的最终版本需要与 9.3 一起回归测试。  
  - **Universe 修改与风险控制**：  
    - 遵守 Story 9.1 的安全语义：空 Universe 表示不再开新仓，而不是回退到默认 Universe；  
    - 通过 Telegram 删除 symbol 时，不应修改任何现有持仓状态，
      仅影响后续信号生成和执行路径（这一点在文案与日志中要反复强调）。

- **与现有架构文档的对齐**  
  - 请参考：  
    - `docs/architecture/06-project-structure-and-mapping.md`：模块职责边界与目录结构；  
    - `docs/architecture/07-implementation-patterns.md`：命名规范、依赖注入模式（例如通过工厂函数创建 handler）、
      以及「配置层 vs 业务层」的分工；  
    - `docs/epics.md#Epic 9: 可配置交易对 Universe & Telegram 管理`：本 Story 的上位 Epic 背景。  
  - 新增代码应放置在：  
    - Telegram 命令解析与分发：`notifications/telegram_commands.py` ；  
    - Universe 管理：复用 `config/universe.py`，避免在 Telegram 模块中自行维护 symbol 列表副本；  
    - 配置与常量：继续依赖 `config/settings.py`，不在业务模块中直接读取环境变量。

- **日志与可观测性建议（与 Story 9.4 对齐）**  
  - 建议为 `/symbols add/remove` 的成功操作使用统一的审计日志格式，例如：  
    - `SYMBOLS_AUDIT: action=ADD symbol=BTCUSDT user_id=... chat_id=... old_universe=[...] new_universe=[...]`；  
  - 对失败/拒绝操作也进行 WARNING 级别日志记录，包含 user_id 与失败原因，
    以便日后审计潜在的恶意操作或误操作。

## Dev Agent Record

### Context Reference

- Epics & Stories: `docs/epics.md#Epic 9: 可配置交易对 Universe & Telegram 管理`（Story 9.2）  
- Universe 抽象实现：`docs/sprint-artifacts/9-1-可配置交易-universe-抽象-paper-live.md`，`config/universe.py`  
- Telegram 配置与管理员权限：`config/settings.py`（`TELEGRAM_ADMIN_USER_ID`，`get_telegram_admin_user_id`）  
- Telegram 命令基础设施：`notifications/telegram_commands.py`（`TelegramCommand`、`CommandResult`、`process_telegram_commands` 等）

### Agent Model Used

Cascade

### Debug Log References

- 建议在本地或测试环境中：  
  - 开启 DEBUG 日志级别，运行一小段时间的 Paper 模式主循环；  
  - 通过 Telegram 发送 `/symbols list` / `/symbols add` / `/symbols remove`，
    观察日志中 Universe 变化与命令处理结果是否与预期一致；  
  - 使用 `./scripts/run_tests.sh` 确认新增测试全部通过且未破坏既有测试。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created for Story 9.2 Telegram `/symbols` 命令接口。  
- 本 Story 文件明确了 `/symbols list/add/remove` 的行为语义、权限模型、
  与 `config.universe` 抽象及 Story 9.3 校验逻辑之间的边界，
  为后续实现提供了完整的开发与测试指引。
- **实现完成 (2025-12-02)**:
  - 在 `notifications/telegram_commands.py` 中实现了 `/symbols` 命令的完整支持
  - 实现了 `handle_symbols_command`, `handle_symbols_list_command`, `handle_symbols_add_command`, `handle_symbols_remove_command` 等 handler 函数
  - 实现了 `validate_symbol_for_universe` 校验函数（占位实现，待 Story 9.3 替换，当前作为统一校验接口）
  - 实现了 `_log_symbols_audit` 审计日志函数，符合 Story 9.4 约定
  - 在 `COMMAND_REGISTRY` 中注册了 `/symbols` 命令的帮助信息
  - 在 `create_kill_resume_handlers` 中注册了 `symbols_handler`
  - 创建了 `tests/test_telegram_symbols_commands.py`，包含 39 个测试用例
  - 所有 842 个测试通过，无回归
  - 已检查 `docs/epics.md`，Epic 9 中对 `/symbols` 的需求描述已覆盖本 Story 的实现范围，本 Story 未修改该文件
  - 当前分支还包含与其他 Story 相关的改动（如 `bot.py`, `core/trading_loop.py`, `execution/executor.py`, `llm/prompt.py`），不属于本 Story 的主要实现范围，此处仅记录
  - 已添加 `docs/sprint-artifacts/sprint-status.yaml`，将本 Story 状态更新为 done

### File List

- `docs/sprint-artifacts/9-2-telegram-symbols-命令接口-list-add-remove.md`（本故事文件）  
- `docs/sprint-artifacts/9-1-可配置交易-universe-抽象-paper-live.md`（前置 Story：Universe 抽象）  
- `docs/epics.md`（Epic 9 与 Story 9.2 的源需求定义）  
- `docs/sprint-artifacts/sprint-status.yaml`（Sprint 状态汇总 - **已修改**，将本 Story 状态更新为 done）  
- `config/settings.py`（Telegram 配置、管理员 ID、backend 配置等）  
- `config/universe.py`（可配置交易 Universe 抽象与运行时覆盖 API，新增 `validate_symbol_for_universe` 校验接口）  
- `notifications/telegram_commands.py`（Telegram 命令解析与处理入口 - **已修改**）  
- `notifications/telegram.py`（Telegram 消息发送与 Markdown 转义工具）  
- `tests/test_universe.py`（Universe 抽象的现有测试，便于对齐行为）  
- `tests/test_telegram_symbols_commands.py`（**新增** - 39 个测试用例验证 `/symbols` 命令行为）
