# Story 9.1: 可配置交易 Universe 抽象（Paper / Live）

Status: done

## Story

As a developer maintaining the trading universe,
I want a configurable symbol universe abstraction for Paper/Live modes,
So that tradable symbols are not hardcoded in settings.py.

作为负责维护交易 Universe 的开发者，
我希望为 Paper / Live 模式提供一个可配置的交易对 Universe 抽象，
从而不再依赖 `config.settings.SYMBOLS` 中的硬编码列表。

## Acceptance Criteria

1. **统一访问接口而非直接依赖常量**  
   - Given 交易主循环运行在 Paper 或 Live 模式下  
   - When 需要获取当前可交易 symbol 列表时  
   - Then 所有调用方（如 `bot.py` / `core/trading_loop.py` / `execution/executor.py`）都通过一个统一的 Universe 访问接口（例如 `get_effective_symbol_universe()`），而不是直接引用 `config.settings.SYMBOLS` 常量。

2. **默认行为与当前 SYMBOLS 完全一致**  
   - Given 没有额外的 Universe 配置或持久化状态  
   - When 通过 Universe 抽象获取当前交易 Universe  
   - Then 返回的 symbol 列表与当前 `config.settings.SYMBOLS` 中的默认值完全一致（如 `ETHUSDT`、`SOLUSDT` 等），不会引入行为变化。

3. **仅影响 Paper / Live 模式，不改变 Backtest 配置路径**  
   - Given 使用 `backtest.py` 进行回测，且通过 `BACKTEST_SYMBOLS` 环境变量或参数指定 symbol  
   - When 运行回测  
   - Then Backtest 仍通过现有的 `BACKTEST_SYMBOLS` / `bot.SYMBOLS` 覆盖逻辑工作，本 Story 引入的 Universe 抽象不会改变回测的 symbol 选择行为。

4. **为后续 Telegram `/symbols` 与 backend 校验预留扩展点**  
   - Given 未来将实现 Story 9.2（Telegram `/symbols` 命令）和 Story 9.3（基于 `MARKET_DATA_BACKEND` 的 symbol 校验）  
   - When 需要对 Universe 做增删或校验时  
   - Then 可以在本 Story 定义的 Universe 抽象与存储层之上扩展，不需要在主循环或业务代码中重新引入硬编码 `SYMBOLS`。

5. **具备最小测试覆盖，验证 Universe 抽象行为**  
   - Given 运行配置 / 环境变量测试（如 `tests/test_config_and_env.py` 的模式）  
   - When 针对 Universe 抽象编写测试用例  
   - Then 至少覆盖：
     - 未配置 Universe 时的默认行为（回退到现有 SYMBOLS）；
     - 在模拟配置或状态下返回覆盖后的 Universe；
     - Backtest 使用 `BACKTEST_SYMBOLS` 时不受影响。

## Tasks / Subtasks

- [x] **Task 1：设计 Universe 抽象与存储形式**  
  - [x] 选择 Universe 的定义位置（建议位于 `config/` 或一个小的状态/配置模块中，避免散落在业务层）。  
  - [x] 定义一个清晰的类型约束（例如 `list[str]` 或封装为 `SymbolUniverse` 类型），并考虑与 `SYMBOL_TO_COIN` / `COIN_TO_SYMBOL` 的对齐。  
  - [x] 决定默认 Universe 的来源：显式保留 `SYMBOLS` 常量作为默认值，Universe 抽象在未配置时直接返回该列表。

- [x] **Task 2：在主循环与执行路径中接入 Universe 抽象**  
  - [x] 在 `core/trading_loop.py` / `bot.py` 中，将直接使用 `SYMBOLS` 的调用替换为对统一 Universe 接口的调用。  
  - [x] 确认 `execution/executor.py` 或其它使用 symbol 列表的模块（如果有）也通过同一接口获取 Universe，而不是各自维护列表。  
  - [x] 保证 Paper / Live 模式下的实际行为与当前硬编码 `SYMBOLS` 完全一致（通过本地 smoke / 单元测试验证）。

- [x] **Task 3：为未来的 Telegram 与校验故事预留集成点**  
  - [x] 在 Universe 抽象中预留读写接口（例如 `get_symbol_universe()` / `set_symbol_universe()` 或等价 API），以便后续 Story 9.2 / 9.3 能安全地在此层之上增删 symbol 并进行校验。  
  - [x] 明确如何与 `MARKET_DATA_BACKEND` 的校验逻辑对接（例如，Universe 修改后由 Story 9.3 负责实际校验）。

- [x] **Task 4：测试与文档对齐**  
  - [x] 在 `tests/` 中补充针对 Universe 抽象的最小测试用例（可放入现有配置相关测试文件或新建测试文件）。  
  - [ ] 在需要时更新 `docs/epics.md` 或相关架构/配置文档，简要说明「可配置交易 Universe 抽象」的存在和默认行为，保持与 Story 9.2–9.4 的描述一致。

## Dev Notes

- **现有硬编码位置与调用链**  
  - 硬编码 `SYMBOLS` 目前定义在：`config/settings.py` 的「SYMBOLS」小节：
    - `SYMBOLS = ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT", "BNBUSDT"]`  
    - `SYMBOL_TO_COIN` / `COIN_TO_SYMBOL` 通过该列表构建。  
  - `core/trading_loop.py` 与 `bot.py` 通过 `from config.settings import SYMBOLS, SYMBOL_TO_COIN, COIN_TO_SYMBOL` 获取交易 Universe。  
  - Backtest 路径（`backtest.py`）在启用 `BACKTEST_SYMBOLS` 时，会覆盖 `bot.SYMBOLS`，这一逻辑需要保持不变。

- **推荐实现方向（非强制，但建议遵循架构模式）**  
  - 在 `config/` 层或一个小的配置模块中定义 Universe 抽象，例如：
    - 提供 `get_effective_symbol_universe()` 函数：
      - 优先读取后续 Story（9.2/9.3）可能写入的 Universe 配置或状态；
      - 如无显式配置，则回退到 `config.settings.SYMBOLS`。  
  - 确保 Universe 抽象只影响 Paper / Live 模式：
    - 回测逻辑继续使用现有的注入/覆盖方式；
    - Universe 抽象本身可以被 Backtest 复用，但不强制。

- **架构与实现模式对齐**  
  - 参考 `docs/architecture/06-project-structure-and-mapping.md`：
    - `config/` 是配置层；
    - `core/` 是核心业务层；
    - 新的抽象应优先放在 `config/` 或单一职责模块中，而不是散落在 `bot.py`。  
  - 遵守 `docs/architecture/07-implementation-patterns.md` 中的规则：
    - 常量命名使用 `UPPER_SNAKE_CASE`；
    - 避免在业务代码中引入新的「临时」数据根目录，Universe 抽象只管理符号列表，不引入新的数据目录。

- **与未来故事的边界**  
  - Story 9.1 仅负责：
    - 抽象出可配置的交易 Universe；
    - 保证默认行为与当前 `SYMBOLS` 一致；
    - 为增删/校验等能力提供清晰扩展点。  
  - Story 9.2–9.4 将在此基础上：
    - 实现 Telegram `/symbols` 命令；
    - 引入基于 `MARKET_DATA_BACKEND` 的 symbol 有效性校验；
    - 定义日志与文档的行为约定。

### Project Structure Notes

- 新增的 Universe 抽象模块应遵循现有目录划分：
  - 若主要是配置与默认值：优先放在 `config/` 下，避免在多个业务模块中重复实现。  
  - 若未来需要持久化 Universe 到状态文件，可考虑复用 `core/state.py` / `core/persistence.py` 的模式，但本 Story 不强制引入持久化。  
- 保持入口脚本（`bot.py`、`backtest.py`）职责单一：
  - 不在入口脚本中直接维护 symbol 列表，而是委托给配置/Universe 抽象。

### References

- [Source: docs/epics.md#Story 9.1: 可配置交易 Universe 抽象（Paper / Live）]
- [Source: docs/prd.md#4.1 交易主循环（Bot）]
- [Source: docs/architecture/06-project-structure-and-mapping.md]
- [Source: docs/architecture/07-implementation-patterns.md]
- [Source: config/settings.py (SYMBOLS / SYMBOL_TO_COIN / COIN_TO_SYMBOL)]

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

Cascade

### Debug Log References

- Universe 抽象与默认行为的本地验证可通过：
  - 在本地运行短时间的 Paper 模式主循环，确认日志中的 symbol 列表与预期一致。  
  - 使用 Backtest + `BACKTEST_SYMBOLS` 验证回测行为未被改变。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created for Story 9.1 symbol universe abstraction.
- Implemented `config/universe.py` with `get_effective_symbol_universe` / `get_effective_coin_universe` and runtime override API, defaulting to `config.settings.SYMBOLS`.
- Refactored `llm/prompt.py`, `bot.py`, `core/trading_loop.py` and `execution/executor.py` to rely on the Universe abstraction instead of hardcoded `SYMBOLS` enumeration in Paper/Live paths.
- Added `tests/test_universe.py` and executed `./scripts/run_tests.sh` (800 tests passed) to validate default behaviour, overrides, and that backtest `BACKTEST_SYMBOLS` flow remains unchanged.

**Code Review 后的改进（2024-12）：**
- 统一从 `config` 包导入 Universe API（符合架构约定 `07-implementation-patterns.md`）。
- 在 `config/universe.py` 模块顶部添加详细文档字符串，明确说明设计约束：仅支持子集过滤、仅内存存储、线程安全模型、持仓安全注意事项。
- 在 `bot.py`、`core/trading_loop.py`、`execution/executor.py` 的 `process_ai_decisions` 中添加 orphaned position 检测：当存在不在当前 Universe 中的持仓时，记录 WARNING 日志。
- 扩展 `tests/test_universe.py`，新增契约测试验证 Universe override 行为和 orphaned position 警告日志。
- **空 Universe 安全语义**：当 Universe override 结果为空（空列表或全部 symbol 无效）时，系统不会对任何标的发起新交易，而不是静默回退到默认全量 Universe。这是风控安全设计，避免误配置导致交易范围意外扩大。需要恢复默认时，请显式调用 `clear_symbol_universe_override()`。
- 全部 803 个测试通过。

### File List

- `docs/sprint-artifacts/9-1-可配置交易-universe-抽象-paper-live.md`（本故事文件）
- `config/settings.py`（保留默认 SYMBOLS 定义，作为 Universe 抽象的默认来源）
- `config/__init__.py`（导出 Universe 抽象 API，供其它模块使用）
- `config/universe.py`（新增：集中管理可配置交易 Universe 抽象与运行时覆盖）
- `core/trading_loop.py`（主交易循环，通过 Universe 抽象获取 coin universe）
- `execution/executor.py`（统一 TradeExecutor 的 coin 枚举逻辑到 Universe 抽象）
- `bot.py`（入口脚本，通过 Universe 抽象记录监控 Universe 并传递给 LLM Prompt 构建）
- `llm/prompt.py`（LLM Prompt 构建模块，通过 Universe 抽象拉取市场快照）
- `tests/test_universe.py`（新增：针对 Universe 抽象的最小单元测试）
