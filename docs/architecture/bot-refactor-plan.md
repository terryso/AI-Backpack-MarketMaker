# LLM-trader-test `bot.py` 重构设计文档

## 1. 背景与目标

- **项目定位**  
  LLM-trader-test 是一个基于 DeepSeek 的多标的加密货币交易系统，支持：
  - 纸上交易（默认）
  - 可选实盘执行（Hyperliquid / Binance Futures / Backpack Futures）
  - Streamlit 仪表盘与历史回放
  - 回测引擎（`backtest.py`）

- **当前问题：`bot.py` 过于臃肿**
  - 单文件 >3000 行，集中了：
    - 环境变量与配置解析
    - 行情数据获取
    - 指标计算 & Prompt 构建
    - LLM 调用与 JSON 决策解析
    - 纸上/实盘执行逻辑
    - 组合状态管理与 CSV/JSON 持久化
    - 统计指标计算（Sortino 等）
    - Telegram 通知、日志等
  - 结果：
    - 心智负担大，新人难以上手
    - 测试粒度偏粗，很多逻辑只能通过集成测试覆盖
    - 未来增加新 backend / 新策略时，改动面大、容易引入回归

- **重构总体目标**
  1. 在**不改变外部行为和 CLI 使用方式**的前提下，拆分 `bot.py` 为若干职责清晰的模块。
  2. 保持现有测试（`tests/`）尽量无需改动或仅做极少适配。
  3. 为后续能力预留空间：
     - 更易接入新执行 backend
     - 更易对接多 LLM / 多策略
     - 更易实现组合级风险控制与 Kill Switch

---

## 2. 范围与不在范围内

- **在本轮重构范围内**
  - 拆分 `bot.py` 为多个模块文件（同一仓库、同一 Python 包层级）。
  - 对内部 import 结构进行调整，使逻辑按功能分层。
  - 适度补充/迁移测试，确保行为一致。

- **不在本轮范围内（仅作为后续演进方向）**
  - 业务逻辑改写（例如策略规则变化、风险参数默认值调整）。
  - 对外接口变更：
    - 启动命令仍为 `python bot.py`。
    - `backtest.py` 仍然 `import bot` 并依赖其公开 API。
  - 引入复杂框架（如依赖注入容器等）。

---

## 3. 目标模块化架构概览

> 注：以下文件名为建议命名，可根据实际情况微调，但职责边界建议保持一致。

- **`bot_config.py`**  
  环境与配置中心：负责所有 env 解析、LLM/Backend 配置、起始资金等。
- **`market_data.py`**  
  行情数据接口：封装 Binance / Backpack 的 kline、funding、OI 访问。
- **`state_io.py`**  
  组合状态与持久化：管理 balance/positions/trade_history/equity_history 及 CSV/JSON 写入。
- **`metrics.py`**  
  绩效与风险指标：Sortino/Sharpe/最大回撤等统一实现。
- **`strategy_core.py`**  
  策略核心：指标计算、Prompt 构建、LLM 调用与 JSON 决策解析。
- **`execution_routing.py`**  
  执行编排：基于 `exchange_client.ExchangeClient` 调用具体 backend（Hyperliquid / Binance Futures / Backpack）。
- **瘦身后的 `bot.py`**  
  应用入口：组装上述模块，负责主交易循环与 CLI 启动逻辑，并对外 re-export 现有公共 API（保持兼容）。

---

## 4. 各模块设计与对外接口

### 4.1 `bot_config.py` —— 配置与环境

- **职责**
  - 负责 `.env` 加载与环境变量解析：
    - 基础键：`BN_API_KEY/BN_SECRET`、`OPENROUTER_API_KEY`、Telegram 相关变量等。
    - Backend 选择：`TRADING_BACKEND`、`MARKET_DATA_BACKEND`、`LIVE_TRADING_ENABLED`、`HYPERLIQUID_LIVE_TRADING` 等。
    - 风险参数：各类 `*_CAPITAL`、`*_MAX_RISK_USD`、`*_MAX_LEVERAGE`、`*_MAX_MARGIN_USD`。
    - LLM 配置：`TRADEBOT_LLM_MODEL`、`TRADEBOT_LLM_TEMPERATURE`、`TRADEBOT_LLM_MAX_TOKENS`、`TRADEBOT_LLM_THINKING`、`LLM_API_*` 系列。
  - 维护默认 System Prompt 与从 env/file 加载自定义 prompt 的逻辑。

- **对外暴露（示例）**
  - 只读配置常量：
    - `TRADING_BACKEND`、`MARKET_DATA_BACKEND`、`IS_LIVE_BACKEND`
    - `PAPER_START_CAPITAL`、`LIVE_START_CAPITAL`、`START_CAPITAL`
    - `BINANCE_FUTURES_LIVE`、`HYPERLIQUID_LIVE_TRADING`、`BACKPACK_FUTURES_LIVE` 等
  - LLM 配置全局变量：
    - `LLM_MODEL_NAME`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`LLM_THINKING_PARAM`
    - `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_API_TYPE`
    - `TRADING_RULES_PROMPT`
  - 工具函数：
    - `refresh_llm_configuration_from_env()`
    - `describe_system_prompt_source()` / `log_system_prompt_info(prefix: str)`

- **兼容性要求**
  - `bot.py` 继续 re-export 必要符号，保证 `backtest.py` 和 tests 中关于 LLM 配置的调用路径不变（例如 `bot.refresh_llm_configuration_from_env()`）。

---

### 4.2 `market_data.py` —— 行情获取

- **职责**
  - 提供统一、可替换的行情数据接口：
    - `BinanceMarketDataClient` wrapping `binance.client.Client`
    - `BackpackMarketDataClient` wrapping Backpack REST API
  - 暴露统一方法：
    - `get_klines(symbol, interval, limit)`（kline）
    - `get_funding_rate_history(symbol, limit)`（Funding）
    - `get_open_interest_history(symbol, limit)`（OI）

- **对外暴露**
  - 类：
    - `BinanceMarketDataClient`
    - `BackpackMarketDataClient`
  - 工厂函数：
    - `get_market_data_client()`：根据 `MARKET_DATA_BACKEND` 和当前 env 决定使用 Binance 或 Backpack。

- **兼容性要求**
  - 保持现有 `bot.py` 中调用 `get_market_data_client()` → client.get_klines(...) 的模式不变，只是迁移实现位置。

---

### 4.3 `state_io.py` —— 组合状态与持久化

- **职责**
  - 管理核心运行状态（目前在 `bot.py` 全局变量中）：
    - `balance`、`positions`、`trade_history`、`equity_history` 等。
  - 路径与文件：
    - `DATA_DIR`（由 `TRADEBOT_DATA_DIR` 或默认 `data/` 推导）
    - `STATE_CSV/JSON`、`TRADES_CSV`、`DECISIONS_CSV`、`MESSAGES_CSV`、`MESSAGES_RECENT_CSV`
  - 提供统一的状态操作函数：
    - CSV 初始化：`init_csv_files()`
    - 记录 equity：`register_equity_snapshot(equity: float)`
    - 记录组合状态：`log_portfolio_state()`
    - 持久化状态：`save_state()`（保存为 JSON/CSV 等）

- **对外暴露**
  - `STATE_CSV`、`TRADES_CSV` 等路径常量（供 backtest、dashboard、脚本使用）。
  - 全局状态访问与重置函数（例如 `reset_state(start_capital: Optional[float])`）。

- **兼容性要求**
  - `bot.py` 继续 re-export 这些路径常量和关键函数，保证：
    - `backtest.py` 中对 `TRADES_CSV`、`reset_state()`、`register_equity_snapshot()` 等调用可用。
    - tests 中直接依赖 `bot.balance/positions` 等全局状态的用例，仍正常工作。

---

### 4.4 `metrics.py` —— 绩效与风险指标

- **职责**
  - 提供所有与收益/风险统计相关的函数（**纯函数实现**）：
    - `calculate_total_equity(...)`（如果目前存在于 `bot.py` 中且较独立）
    - `calculate_sortino_ratio(equity_history, interval_seconds, risk_free_rate)`（目前 backtest 在用）
    - （可选）未来统一 Sharpe/最大回撤等实现，供 dashboard/backtest 复用。

- **对外暴露**
  - 上述函数，独立于任何全局状态/IO，只依赖参数。

- **兼容性要求**
  - 现阶段 `backtest.py` 仍通过 `bot.calculate_sortino_ratio` 调用：
    - 由 `bot.py` from `metrics` import 并 re-export `calculate_sortino_ratio` 来保持兼容。

---

### 4.5 `strategy_core.py` —— 策略与 LLM 决策

- **职责**
  - 行情数据 + 组合状态 → 技术指标计算（EMA/RSI/MACD/ATR 等）。
  - 构建 LLM Prompt：
    - 将多时间框架行情、仓位、PnL、风险参数等组织成结构化 prompt。
  - LLM 调用：
    - 根据来自 `bot_config` 的 LLM 配置（base URL、key、model、temperature、thinking 参数等）调用 DeepSeek / OpenAI 兼容接口。
    - 解析 LLM 返回的 JSON，校验字段与取值范围（`signal/side/quantity/stop_loss/profit_target/confidence/risk_usd` 等）。
  - 将解析后的决策转化为上层可用的结构（例如 `{coin: Decision}` 字典）。

- **对外暴露（示例）**
  - `format_prompt_for_deepseek(...) -> str`
  - `call_deepseek_api(prompt: str) -> Dict[str, Any]` / `-> Optional[Dict[str, Any]]`
  - `process_ai_decisions(decisions: Dict[str, Any]) -> None`（或返回结构供主循环使用）

- **兼容性要求**
  - 对 `bot.py` 来说，接口保持“黑盒”：只关心输入（当前行情+仓位）和输出（决策），不关心内部实现。

---

### 4.6 `execution_routing.py` —— 执行路径与后端切换

- **职责**
  - 将 LLM 决策（entry/close、size、价格、杠杆、liquidity）转化为底层交易调用：
    - 纸上路径：更新本地 `positions`、`balance` 等，并写入 `trade_history`。
    - 实盘路径：使用 `exchange_client.get_exchange_client` 获取具体实现（Hyperliquid / Binance Futures / Backpack），并调用其 `place_entry/close_position`。
  - 维护与风险约束的连接：
    - 单笔风险（risk_usd）与全局限制（live/paper 起始资金、max risk/max leverage 等）的校验。

- **对外暴露（示例）**
  - `execute_entry(decision, state, config) -> EntryResult/None`
  - `execute_close(decision, state, config) -> CloseResult/None`

- **兼容性要求**
  - 对 `bot.py` 主循环而言，执行层成为一个相对稳定的接口，方便未来引入更多 backend 或策略。

---

### 4.7 瘦身后的 `bot.py` —— 应用层入口

- **职责**
  - 初始化：
    - logging、`.env`、数据目录等。
    - `HyperliquidTradingClient` / Binance Futures exchange 客户端工厂（可以部分迁移到单独工厂模块，但第一阶段可暂留在此）。
  - 主交易循环：
    1. 拉取行情（借助 `market_data`）。
    2. 计算指标与 Prompt（借助 `strategy_core`）。
    3. 调用 LLM 并解析决策。
    4. 通过 `execution_routing` 执行纸上/实盘路径。
    5. 更新状态并调用 `state_io` 进行持久化与日志。
  - CLI 与工具入口：
    - 仍支持直接 `python bot.py` 运行。
    - 未来可添加 `--check-config` 等子命令。

- **兼容性要求**
  - 保持：
    - `if __name__ == "__main__": main()` 入口。
    - `backtest.py` 和 tests 期望的 `bot` 公共 API 名称不变，通过 re-export 向下兼容。

---

## 5. 渐进式迁移计划（Phase by Phase）

### Phase 0：基线确认

- **目标**
  - 在重构前配置一个基线，确保任何改动都能通过统一的验证。

- **步骤**
  1. 本地运行：
     - `pytest`（全部单测）
     - 至少一次短 backtest：`python backtest.py`（使用默认 env）。
  2. 记录：
     - 回测结果中关键指标（Sortino、max_drawdown、总收益、交易笔数等）。
     - 当前 `bot.py` 对外暴露的函数/变量清单（建议简单列一下供对照）。

---

### Phase 1：抽取 `metrics.py`（低风险起步）

- **目标**
  - 将纯统计函数迁移到独立模块，验证“拆分 + re-export”模式。

- **步骤**
  1. 在项目根目录创建 `metrics.py`。
  2. 从 `bot.py` 提取：
     - `calculate_sortino_ratio(...)` 及依赖的纯函数（若有）。
  3. `bot.py`：
     - `from metrics import calculate_sortino_ratio`  
     - 保留 `calculate_sortino_ratio` 在 `bot.py` 的命名空间中（re-export）。
  4. 运行 `pytest` + 一个短 backtest。

- **验收标准**
  - 所有测试通过。
  - backtest 的 `sortino` 结果与 Phase 0 一致（在浮点误差范围内）。

---

### Phase 2：抽取 `bot_config.py`（配置中心）

- **目标**
  - 将 env & LLM 配置集中管理，减轻 `bot.py` 顶部复杂度。

- **步骤**
  1. 创建 `bot_config.py`，迁移：
     - `_parse_bool_env/_parse_float_env/_parse_int_env/_parse_thinking_env`
     - 所有 env 解析和配置常量定义（`TRADING_BACKEND`、`MARKET_DATA_BACKEND`、`START_CAPITAL`、LLM 配置等）。
     - `_load_system_prompt` 及 `TRADING_RULES_PROMPT`。
     - `refresh_llm_configuration_from_env`、`describe_system_prompt_source`、`log_system_prompt_info`。
  2. `bot.py` 中删去相关实现，改为：
     - `from bot_config import *`（可更精细地导入具体名称）。
  3. 确保：
     - `backtest.py` 对 `bot.refresh_llm_configuration_from_env()`、`bot.log_system_prompt_info()` 等调用仍可用（通过 `bot.py` re-export）。
  4. 运行测试与短 backtest。

- **验收标准**
  - 行为和日志输出与 Phase 0 一致；
  - 未引入新的配置解析 Bug（通过测试 & 手动 spot-check）。

---

### Phase 3：抽取 `market_data.py`

- **目标**
  - 分离行情数据访问逻辑，简化 `bot.py` 对外部 API 的直接接触。

- **步骤**
  1. 创建 `market_data.py`，迁移：
     - `BinanceMarketDataClient`
     - `BackpackMarketDataClient`
     - `get_market_data_client()`
  2. `bot.py` 顶部改为：
     - `from market_data import get_market_data_client, BinanceMarketDataClient, BackpackMarketDataClient`
  3. 确保所有对市场数据的访问入口都统一从该模块调用。
  4. 运行测试与短 backtest。

- **验收标准**
  - 行为一致；对 Binance/Backpack 的请求路径不变（可通过日志简单验证）。

---

### Phase 4：抽取 `state_io.py`

- **目标**
  - 让组合状态与 CSV/JSON 处理独立出来，减轻 `bot.py` 全局变量散落的问题。

- **步骤**
  1. 创建 `state_io.py`，迁移：
     - `DATA_DIR` 与所有 CSV/JSON 路径常量
     - 全局状态（`balance/positions/trade_history/equity_history` 等）以及相关辅助函数：
       - `init_csv_files`
       - `log_portfolio_state`
       - `register_equity_snapshot`
       - `save_state`
       - `reset_state`（如果目前存在）
  2. 在 `bot.py` 中：
     - 通过 `from state_io import ...` 使用这些函数和变量；
     - 按需 re-export 需要给 backtest/tests 使用的名称。
  3. 运行全部测试与至少一次 backtest。

- **验收标准**
  - 所有关于 PnL/Equity、状态管理的测试通过；
  - backtest 结果与 Phase 0 一致或仅在日志层面有轻微差异。

---

### Phase 5：抽取 `strategy_core.py` 与 `execution_routing.py`（中等风险）

- **目标**
  - 将“策略 + LLM 调用”与“执行/风控”从 `bot.py` 中分离，形成可独立推演和优化的部分。

- **步骤（可分两子阶段）**

  - **5A：`strategy_core.py`**
    1. 迁移：
       - 指标计算函数。
       - Prompt 构造函数（如 `format_prompt_for_deepseek`）。
       - LLM 调用函数（如 `call_deepseek_api`、决策解析逻辑）。
    2. 确保主循环只调用统一入口，例如：
       - `prompt = strategy_core.format_prompt_for_deepseek(...)`
       - `decisions = strategy_core.call_deepseek_api(prompt)`
  - **5B：`execution_routing.py`**
    1. 迁移：
       - 将解析后的 `decisions` 映射为 Entry/Close 执行的逻辑。
       - 纸上与实盘分支路径（调用 `exchange_client.get_exchange_client`、Hyperliquid/Binance/Backpack 客户端）。
    2. 主循环只关心：
       - “把决策丢给执行层；得到结果后更新状态”。

- **验收标准**
  - 所有与进出场、PnL、止损/止盈相关的测试（如 `test_entry_and_close.py`, `test_stop_loss_take_profit.py`, `test_pnl_and_equity.py` 等）保持通过。
  - 手工跑一段时间的真实/模拟循环（至少纸上模式），观察行为无异常。

---

## 6. 测试与验收策略

- **自动化测试**
  - 每个 Phase 结束时，都必须：
    - 运行 `pytest` 全套测试；
    - 至少运行一次 `python backtest.py`（短时间窗口即可）。

- **行为基线**
  - 以 Phase 0 的回测结果为基线，对比：
    - 总收益（%）
    - Sortino
    - 最大回撤
    - 总交易数
  - 若存在差异，应先排查原因，再判断是否可接受。

- **日志与错误检查**
  - 留意日志中是否出现新的 WARNING/ERROR（特别是 env 解析和 backend 初始化部分）。

---

## 7. 风险与规避

- **潜在风险**
  - 函数/变量名在迁移过程中被改动，导致 `backtest.py` 或 tests 无法导入。
  - 由于全局状态位置改变，某些测试对 `bot` 内部状态的假设失效。
  - 在高耦合区域（策略 + 执行）拆分时牵连较大，容易出现细微逻辑回归。

- **规避策略**
  - 严格分 Phase，每次只动一类职责。
  - 尽量通过 `bot.py` re-export 原符号，减少对下游代码的冲击。
  - 每次改动都坚持“先基线、后比较”的原则。

---

## 8. 后续演进方向（超出本轮重构，但依赖这次奠基）

在上述拆分完成后，可以更容易实现：

1. **多 LLM / 多策略对比**
   - 在 `strategy_core` 中统一一个 `generate_decisions(market_snapshot) -> List[DecisionBundle]` 接口，支持：
     - 同时调用多个 LLM / 多种 Prompt；
     - 在执行层实现策略投票或选择逻辑。

2. **组合级风险控制与 Kill Switch**
   - 在 `state_io` + `metrics` 上层构建：
     - 单日/滚动时间窗最大回撤；
     - 一键 Kill Switch 文件/标志位，主循环自动停单。

3. **配置自检工具**
   - 基于 `bot_config` 提供一个：
     - `python bot.py --check-config` 或 `scripts/check_config.py`，输出当前 backend/LLM/env 配置状态。

---

## 9. 总结

- 本重构文档定义了：
  - 目标模块划分与各自职责；
  - 渐进式迁移步骤（Phase 0–5）；
  - 测试与验收标准；
  - 潜在风险与规避策略。
- 文档设计为**可独立阅读**，不依赖当前对话历史，后续任何时间都可以据此继续实施重构。
