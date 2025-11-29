## 2. 组件视图

### 2.1 配置层（config/）

**模块**：`config/settings.py`

职责：

- 统一加载 `.env` 与环境变量，解析 API Key、LLM 模型配置、风险参数等。
- 提供所有配置常量的单一来源：
  - **API 密钥**：Binance、OpenRouter、Telegram、Hyperliquid、Backpack。
  - **交易配置**：`TRADING_BACKEND`、`MARKET_DATA_BACKEND`、`LIVE_TRADING_ENABLED`。
  - **LLM 配置**：模型名称、温度、最大 token、API 类型（OpenRouter/OpenAI）。
  - **指标参数**：EMA、RSI、MACD 周期设置。
  - **数据路径**：CSV/JSON 文件路径。

导出接口（通过 `config/__init__.py`）：

```python
from config import (
    DATA_DIR, TRADING_BACKEND, LIVE_TRADING_ENABLED,
    LLM_MODEL_NAME, LLM_TEMPERATURE, SYMBOLS, ...
)
```

### 2.2 核心业务层（core/）

#### 2.2.1 状态管理（core/state.py）

职责：

- 管理全局交易状态：`balance`、`positions`、`trade_history`、`equity_history`。
- 提供状态访问与修改的函数式接口：
  - `get_balance()` / `set_balance()` / `update_balance()`
  - `get_positions()` / `set_position()` / `remove_position()`
  - `load_state()` / `save_state()` / `reset_state()`
- 支持可注入的时间提供器（用于回测）：`set_time_provider()`。

#### 2.2.2 持久化（core/persistence.py）

职责：

- CSV/JSON 文件的读写操作：
  - `init_csv_files_for_paths()`：初始化 CSV 文件结构。
  - `append_portfolio_state_row()` / `append_trade_row()`：追加记录。
  - `save_state_to_json()` / `load_state_from_json()`：状态序列化。
  - `load_equity_history_from_csv()`：加载权益历史。

#### 2.2.3 指标计算（core/metrics.py）

职责：

- 组合级别的指标计算：
  - `calculate_sortino_ratio()`：计算 Sortino 比率。
  - `calculate_pnl_for_price()`：计算指定价格的盈亏。
  - `calculate_unrealized_pnl_for_position()`：计算未实现盈亏。
  - `calculate_total_margin_for_positions()`：计算总保证金。

#### 2.2.4 交易循环（core/trading_loop.py）

职责：

- 核心交易循环逻辑的实现。
- 协调各模块完成一次完整的交易迭代：
  1. 拉取多周期行情。
  2. 调用 `strategy/` 计算技术指标。
  3. 调用 `llm/` 构建 Prompt 并获取决策。
  4. 调用 `execution/` 执行交易。
  5. 更新状态并持久化。

### 2.3 策略层（strategy/）

#### 2.3.1 技术指标（strategy/indicators.py）

职责：

- 技术指标计算函数：
  - `calculate_rsi_series()`：RSI 序列计算（Wilder 平滑）。
  - `calculate_atr_series()`：ATR 序列计算。
  - `add_indicator_columns()`：为 DataFrame 添加 EMA、RSI、MACD 列。
  - `calculate_indicators()`：计算并返回最新指标行。
  - `round_series()`：数值精度处理。

#### 2.3.2 市场快照（strategy/snapshot.py）

职责：

- `build_market_snapshot()`：构建包含多时间框架行情与指标的市场快照，供 LLM Prompt 使用。

### 2.4 LLM 层（llm/）

#### 2.4.1 Prompt 构建（llm/prompt.py）

职责：

- `build_trading_prompt()`：构造包含多时间框架行情 + 仓位 + 风险约束的完整 Prompt。

#### 2.4.2 响应解析（llm/parser.py）

职责：

- `parse_llm_json_decisions()`：解析 LLM 返回的 JSON 决策。
- `recover_partial_decisions()`：从不完整的 JSON 响应中恢复部分决策。

#### 2.4.3 API 客户端（llm/client.py）

职责：

- `call_deepseek_api()`：调用 LLM API（支持 OpenRouter 和 OpenAI 兼容接口）。

### 2.5 执行层（execution/）

#### 2.5.1 交易执行器（execution/executor.py）

职责：

- `TradeExecutor` 类：统一的交易执行接口，通过依赖注入支持不同执行模式。
  - `execute_entry()`：执行入场交易。
  - `execute_close()`：执行平仓交易。
  - `process_hold()`：处理持仓信号。
  - `process_decisions()`：批量处理 AI 决策。
  - `check_stop_loss_take_profit()`：检查并执行止损止盈。

#### 2.5.2 路由逻辑（execution/routing.py）

职责：

- 交易计划计算与路由：
  - `EntryPlan` / `ClosePlan`：交易计划数据类。
  - `compute_entry_plan()` / `compute_close_plan()`：计算交易参数。
  - `route_live_entry()` / `route_live_close()`：路由到具体交易所执行。
  - `check_stop_loss_take_profit_for_positions()`：批量检查 SL/TP。

### 2.6 交易所层（exchange/）

#### 2.6.1 基础定义（exchange/base.py）

职责：

- 定义统一的交易所接口与数据结构：
  - `EntryResult`：入场结果 dataclass。
  - `CloseResult`：平仓结果 dataclass。
  - `ExchangeClient`：交易所客户端 Protocol。

#### 2.6.2 客户端工厂（exchange/factory.py）

职责：

- 交易所客户端的创建与管理：
  - `get_exchange_client()`：根据配置获取对应的交易所客户端。
  - `get_binance_client()` / `get_hyperliquid_trader()`：获取特定客户端。
  - `get_market_data_client()` / `set_market_data_client()`：市场数据客户端管理。

#### 2.6.3 交易所实现

- **exchange/hyperliquid.py**：`HyperliquidExchangeClient` - Hyperliquid 永续合约适配器。
- **exchange/binance.py**：`BinanceFuturesExchangeClient` - Binance 合约适配器。
- **exchange/backpack.py**：`BackpackFuturesExchangeClient` - Backpack 交易所适配器。
- **exchange/hyperliquid_client.py**：原始 Hyperliquid SDK 封装（兼容层）。

#### 2.6.4 市场数据（exchange/market_data.py）

职责：

- 市场数据获取的统一接口：
  - `BinanceMarketDataClient`：Binance K 线数据获取。
  - `BackpackMarketDataClient`：Backpack K 线数据获取。

### 2.7 显示层（display/）

#### 2.7.1 消息格式化（display/formatters.py）

职责：

- 交易信号消息的格式化：
  - `build_entry_signal_message()`：构建入场信号消息。
  - `build_close_signal_message()`：构建平仓信号消息。

#### 2.7.2 投资组合显示（display/portfolio.py）

职责：

- 投资组合状态的格式化显示。

### 2.8 通知层（notifications/）

#### 2.8.1 Telegram 通知（notifications/telegram.py）

职责：

- Telegram 消息发送：
  - 迭代摘要通知。
  - 交易信号通知。
  - 错误告警通知。

#### 2.8.2 日志记录（notifications/logging.py）

职责：

- 统一的日志配置与格式化。
- 日志级别管理。

### 2.9 工具层（utils/）

**模块**：`utils/text.py`

职责：

- 文本处理工具函数：
  - `strip_ansi_codes()`：移除 ANSI 颜色代码。
  - `escape_markdown()`：转义 Telegram Markdown 特殊字符。

### 2.10 入口层

#### 2.10.1 交易主循环（bot.py）

职责：

- 作为交易系统的主入口与协调层。
- 组合各模块功能，启动交易循环。
- 保留向后兼容的函数包装（供测试使用）。

#### 2.10.2 回测引擎（backtest.py）

职责：

- 配置回测时间段、K 线周期、LLM 参数与初始资金（基于 `BACKTEST_*` 环境变量）。
- 使用 Binance API 下载所需时间窗口内的历史 K 线数据，并缓存到 `data-backtest/cache/`。
- 构建 `HistoricalBinanceClient`：
  - 对 `bot` 来说看起来像真实 Binance Client，但底层从缓存 DataFrame 取数据。
- 通过 **依赖注入（替换 Binance Client 与数据目录）** 达到「逻辑复用」，避免复制交易逻辑。
- 回测输出布局与线上 `data/` 相似，使得仪表盘可指向回测目录进行分析。

#### 2.10.3 仪表盘（dashboard.py）

职责：

- 加载 `.env`，获取 `BN_API_KEY` / `BN_SECRET`（可选），以便在界面中展示实时价格对比。
- 读取：
  - `portfolio_state.csv`
  - `trade_history.csv`
  - `ai_decisions.csv`
  - `ai_messages.csv`
- 计算：
  - 实现盈亏与未实现盈亏。
  - Sharpe 与 Sortino 比率（按组合净值轨迹计算，考虑风险自由率）。
- 渲染：
  - 账户余额与净值、回报率、Sharpe/Sortino 等关键指标卡片。
  - 净值 vs BTC Buy&Hold 曲线对比图（使用 Altair）。
  - 当前持仓与基于实时价格的未实现盈亏。
  - 交易与 AI 决策表格。

### 2.11 回放与工具（replay/ 与 scripts/）

- **replay/**：
  - `build_replay_site.py` + `index.html`：将历史 CSV/JSON 转化为可交互或静态页面回放，提供「故事化」视角。
- **scripts/**：
  - `recalculate_portfolio.py`：从交易历史重放组合，修正 `portfolio_state`。
  - `manual_hyperliquid_smoke.py`：Hyperliquid 实盘连通性测试。
  - `manual_binance_futures_smoke.py`：Binance Futures 连通性测试。
  - `manual_backpack_futures_smoke.py`：Backpack 连通性测试。
  - `run_backtest_docker.sh`：封装 Docker 运行逻辑，方便并行回测。
