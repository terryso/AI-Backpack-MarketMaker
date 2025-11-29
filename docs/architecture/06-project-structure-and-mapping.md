## 6. 项目结构与源码树

```text
LLM-trader-test/
├── bot.py                      # 交易主入口：协调各模块，启动交易循环
├── backtest.py                 # 回测入口：重放历史 K 线，重用核心逻辑
├── dashboard.py                # Streamlit 仪表盘：读取 data/ 下 CSV/JSON 进行可视化
│
├── config/                     # 配置层
│   ├── __init__.py
│   └── settings.py             # 统一配置加载
│
├── core/                       # 核心业务层
│   ├── __init__.py
│   ├── state.py                # 状态管理
│   ├── persistence.py          # 状态持久化
│   ├── metrics.py              # 指标计算
│   └── trading_loop.py         # 核心交易循环
│
├── exchange/                   # 交易所层
│   ├── __init__.py
│   ├── base.py                 # 抽象接口（ExchangeClient Protocol）
│   ├── factory.py              # 客户端工厂
│   ├── hyperliquid.py          # Hyperliquid 适配器
│   ├── binance.py              # Binance Futures 适配器
│   ├── backpack.py             # Backpack 适配器
│   ├── hyperliquid_client.py   # 原始 SDK 封装（兼容层）
│   └── market_data.py          # 市场数据客户端
│
├── execution/                  # 执行层
│   ├── __init__.py
│   ├── executor.py             # 统一交易执行器
│   └── routing.py              # 路由逻辑
│
├── strategy/                   # 策略层
│   ├── __init__.py
│   ├── indicators.py           # 技术指标计算
│   └── snapshot.py             # 市场快照构建
│
├── llm/                        # LLM 层
│   ├── __init__.py
│   ├── client.py               # LLM API 调用
│   ├── prompt.py               # Prompt 构建
│   └── parser.py               # 响应解析
│
├── display/                    # 显示层
│   ├── __init__.py
│   ├── formatters.py           # 消息格式化
│   └── portfolio.py            # 投资组合显示
│
├── notifications/              # 通知层
│   ├── __init__.py
│   ├── telegram.py             # Telegram 通知
│   └── logging.py              # 日志记录
│
├── utils/                      # 工具层
│   ├── __init__.py
│   └── text.py                 # 文本处理工具
│
├── prompts/                    # Prompt 模板目录
├── scripts/                    # 工具脚本
├── replay/                     # 回放站点
├── tests/                      # 测试目录
├── data/                       # 运行时数据目录
├── data-backtest/              # 回测输出目录
├── docs/                       # 文档目录
├── .env.example                # 环境变量示例
├── Dockerfile                  # Docker 构建配置
└── requirements.txt            # Python 依赖清单
```

> 说明：`data/`、`data-backtest/` 等目录为运行期生成内容，通常不会提交到版本库中。

---

## 6.2 PRD 功能块到架构组件的映射

下表将 PRD 中的核心功能块映射到具体代码组件与数据路径，便于验证「每个功能需求都有清晰的架构支撑」。

| PRD 功能块 | 主要实现组件 | 关键数据/目录 | 说明 |
| ---------- | ------------ | ------------- | ---- |
| 交易主循环（4.1） | `bot.py`, `core/trading_loop.py`, `execution/executor.py` | `data/portfolio_state.*`, `data/trade_history.csv` | 协调由 `bot.py`，核心逻辑在 `core/trading_loop.py`，执行由 `execution/` 处理。 |
| 风险控制与资金管理（4.2） | `execution/routing.py`, `core/metrics.py` | `trade_history.csv`, `portfolio_state.*` | 风险计算在 `execution/routing.py`，指标计算在 `core/metrics.py`。 |
| LLM 配置与 Prompt 管理（4.3） | `config/settings.py`, `llm/prompt.py`, `llm/client.py` | `.env`, `prompts/` | 配置在 `config/`，Prompt 构建在 `llm/prompt.py`，API 调用在 `llm/client.py`。 |
| 数据持久化与日志（4.4） | `core/persistence.py`, `core/state.py` | `data/` | 状态管理在 `core/state.py`，持久化在 `core/persistence.py`。 |
| 仪表盘（4.5） | `dashboard.py`, `display/` | `data/*.csv` | Streamlit 应用读取数据，`display/` 提供格式化支持。 |
| 回测（4.6） | `backtest.py`, `exchange/market_data.py` | `data-backtest/` | 通过注入 `HistoricalBinanceClient` 重用核心逻辑。 |
| Telegram 通知（4.7） | `notifications/telegram.py`, `display/formatters.py` | 无持久化 | 格式化在 `display/formatters.py`，发送在 `notifications/telegram.py`。 |
| 交易所实盘集成（4.8） | `exchange/hyperliquid.py`, `exchange/binance.py`, `exchange/backpack.py` | 无本地数据 | 各适配器实现统一的 `ExchangeClient` Protocol。 |
| 非功能：性能与稳定性（5.1） | 各模块 | `data/`, `data-backtest/` | 模块化架构支持解耦演进，稳定性由重试逻辑保证。 |
| 非功能：安全性（5.2） | `config/settings.py`, `.env` | `.env`（未提交） | 所有敏感信息通过环境变量注入，默认不开启实盘。 |
| 非功能：可观测性（5.3） | `core/persistence.py`, `dashboard.py`, `replay/` | `data/` | 完整决策与状态记录，支持可视化与回放。 |

> 若后续在 PRD 中新增功能块，应在本表中补充行，并在相应代码组件中实现对应的架构支撑。

此外：

- 交易 backend 与 live 模式的配置入口集中在根目录 `.env.example` 与 README 的「Trading Backends & Live Mode Configuration」小节。
- 新增交易所适配器时，统一通过 `exchange/base.py` 中的 `ExchangeClient` Protocol 与 `exchange/factory.py` 中的工厂函数进行扩展。
