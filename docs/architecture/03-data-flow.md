## 3. 数据流

### 3.1 实时交易路径

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           数据输入阶段                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  exchange/market_data.py                                                │
│  ├── BinanceMarketDataClient.get_klines()                              │
│  └── BackpackMarketDataClient.get_klines()                             │
│                          ↓                                              │
│  core/persistence.py                                                    │
│  └── load_state_from_json() → 当前仓位与历史表现                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          策略分析阶段                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  strategy/indicators.py                                                 │
│  └── calculate_indicators() → EMA/RSI/MACD/ATR                         │
│                          ↓                                              │
│  strategy/snapshot.py                                                   │
│  └── build_market_snapshot() → 多时间框架市场快照                        │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          LLM 决策阶段                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  llm/prompt.py                                                          │
│  └── build_trading_prompt() → 构建完整 Prompt                           │
│                          ↓                                              │
│  llm/client.py                                                          │
│  └── call_deepseek_api() → OpenRouter/OpenAI API 调用                   │
│                          ↓                                              │
│  llm/parser.py                                                          │
│  └── parse_llm_json_decisions() → JSON 决策解析                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          交易执行阶段                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  execution/executor.py                                                  │
│  └── TradeExecutor.process_decisions()                                 │
│                          ↓                                              │
│  execution/routing.py                                                   │
│  ├── compute_entry_plan() / compute_close_plan()                       │
│  └── route_live_entry() / route_live_close()                           │
│                          ↓                                              │
│  exchange/*.py (根据 TRADING_BACKEND 选择)                              │
│  ├── HyperliquidExchangeClient.place_entry()                           │
│  ├── BinanceFuturesExchangeClient.place_entry()                        │
│  └── BackpackFuturesExchangeClient.place_entry()                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          状态持久化阶段                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  core/state.py                                                          │
│  └── save_state() → 更新内存状态                                        │
│                          ↓                                              │
│  core/persistence.py                                                    │
│  ├── append_portfolio_state_row() → portfolio_state.csv                │
│  ├── append_trade_row() → trade_history.csv                            │
│  └── save_state_to_json() → portfolio_state.json                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          通知与显示阶段                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  display/formatters.py                                                  │
│  └── build_entry_signal_message() / build_close_signal_message()       │
│                          ↓                                              │
│  notifications/telegram.py                                              │
│  └── send_telegram_message() → Telegram 通知                           │
│                          ↓                                              │
│  dashboard.py                                                           │
│  └── Streamlit 仪表盘 → 用户界面                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 模块间依赖关系

```
┌─────────────┐
│   bot.py    │ ─────────────────────────────────────┐
└──────┬──────┘                                      │
       │                                             │
       ▼                                             ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐
│   config/   │◄───│    core/    │◄───│     execution/      │
└─────────────┘    └──────┬──────┘    └──────────┬──────────┘
                         │                      │
                         ▼                      ▼
                  ┌─────────────┐    ┌─────────────────────┐
                  │  exchange/  │◄───│      strategy/      │
                  └─────────────┘    └──────────┬──────────┘
                                                │
                                                ▼
                  ┌─────────────┐    ┌─────────────────────┐
                  │   display/  │◄───│        llm/         │
                  └─────────────┘    └─────────────────────┘
                         │
                         ▼
                  ┌─────────────┐    ┌─────────────────────┐
                  │notifications│    │       utils/        │
                  └─────────────┘    └─────────────────────┘
```

### 3.3 回测路径

1. **配置与数据准备**：
   - 通过环境变量描述回测时间段、间隔与 LLM 设置。
   - Binance K 线 → `data-backtest/cache/`。
2. **执行与日志**：
   - `HistoricalBinanceClient` 替换 `exchange/market_data.py` 中的行情来源。
   - 通过 `set_market_data_client()` 注入历史数据客户端。
   - 其他流程与实时交易类似，但数据输出到 `data-backtest/run-*/`。
3. **分析与复用**：
   - 仪表盘或外部工具指向回测目录进行表现分析。

### 3.4 交易所后端选择

系统通过 `TRADING_BACKEND` 环境变量选择交易执行后端：

| 后端值 | 交易所客户端 | 市场数据源 | 说明 |
|--------|-------------|-----------|------|
| `paper` | 纸上交易（内存） | Binance | 默认模式，无实际下单 |
| `hyperliquid` | `HyperliquidExchangeClient` | Binance | Hyperliquid 永续合约 |
| `binance_futures` | `BinanceFuturesExchangeClient` | Binance | Binance 合约 |
| `backpack` | `BackpackFuturesExchangeClient` | Backpack | Backpack 交易所 |
