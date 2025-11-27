## 6. 项目结构与源码树

```text
LLM-trader-test/
├── bot.py                # 交易主循环：行情拉取、LLM 决策、风控与交易执行，写入 data/
├── backtest.py           # 回测入口：重放历史 K 线，重用 bot 逻辑并写入 data-backtest/
├── dashboard.py          # Streamlit 仪表盘：读取 data/ 下 CSV/JSON 进行可视化
├── hyperliquid_client.py # Hyperliquid 实盘执行适配器：负责 tick size、价格正规化和下单
├── scripts/
│   ├── recalculate_portfolio.py     # 根据 trade_history.csv 重算 portfolio_state.json
│   ├── manual_hyperliquid_smoke.py  # 小额 Hyperliquid 实盘连通性 smoke test
│   └── run_backtest_docker.sh       # 在 Docker 环境中批量运行回测
├── data/                  # 运行时生成的数据目录（默认，通过 TRADEBOT_DATA_DIR 覆盖）
├── data-backtest/         # 回测输出目录（backtest.py 每个 run-*/ 子目录）
├── docs/
│   ├── prd.md             # 反向工程 PRD（功能与非功能需求）
│   ├── architecture.md    # 架构文档入口（链接到分片）
│   └── architecture/
│       ├── index.md
│       ├── 01-overview-and-deployment.md
│       ├── 02-components.md
│       ├── 03-data-flow.md
│       ├── 04-integrations.md
│       ├── 05-evolution.md
│       ├── 06-project-structure-and-mapping.md
│       └── 07-implementation-patterns.md
├── .bmad/                 # BMAD/BMM 模块与工作流配置
├── .env.example           # 环境变量示例文件
├── Dockerfile             # Docker 构建与运行配置（Python 3.13.3-slim 基础镜像）
└── requirements.txt       # Python 依赖清单
```

> 说明：`data/`、`data-backtest/`、`data-backtest/run-*/` 等目录多为运行期生成内容，通常不会提交到版本库中。

---

## 6.2 PRD 功能块到架构组件的映射

下表将 PRD 中的核心功能块映射到具体代码组件与数据路径，便于验证「每个功能需求都有清晰的架构支撑」。

| PRD 功能块 | 主要实现组件 | 关键数据/目录 | 说明 |
| ---------- | ------------ | ------------- | ---- |
| 交易主循环（4.1） | `bot.py` | `data/portfolio_state.*`, `data/trade_history.csv`, `data/ai_decisions.csv`, `data/ai_messages.csv` | 定时调度、行情拉取、指标计算、Prompt 构建、LLM 调用、决策解析与执行均在此集中实现。 |
| 风险控制与资金管理（4.2） | `bot.py` | 同上（特别是 `trade_history.csv`、`portfolio_state.*`） | 单笔风险、止损/止盈、仓位规模与杠杆逻辑在 Bot 内部封装，由 CSV/JSON 记录结果。 |
| LLM 配置与 Prompt 管理（4.3） | `bot.py` + `.env` / Prompt 文件 | `.env` / `TRADEBOT_SYSTEM_PROMPT_FILE` 指向的文件 | LLM 模型名、温度、thinking 参数、系统 Prompt 的解析与热更新逻辑集中在 `bot.py` 顶部配置区。 |
| 数据持久化与日志（4.4） | `bot.py`, `scripts/recalculate_portfolio.py` | `data/` | Bot 负责写入 CSV/JSON，recalculate 脚本负责从 trade_history 重建组合状态，与 PRD 中「可复现性」和「审计」要求对应。 |
| 仪表盘（4.5） | `dashboard.py` | `data/portfolio_state.csv`, `data/trade_history.csv`, `data/ai_decisions.csv`, `data/ai_messages.csv` | Streamlit 应用从 data/ 中读取文件并计算 Sharpe/Sortino 等指标，对应 PRD 的可视化与可观测性需求。 |
| 回测（4.6） | `backtest.py`, `bot.py` | `data-backtest/cache/`, `data-backtest/run-*/` | 回测通过 HistoricalBinanceClient 重用 Bot 逻辑，输出与 live 近似的数据布局，满足「策略评估」类需求。 |
| Telegram 通知（4.7） | `bot.py` | 无持久化目录（通过 Telegram API 推送） | `send_telegram_message` 与 `notify_error` 实现迭代摘要与错误通知，对应 PRD 的运维与信号通知场景。 |
| Hyperliquid 实盘集成（4.8） | `hyperliquid_client.py`, `bot.py`, `scripts/manual_hyperliquid_smoke.py` | 无本地数据目录（主要依赖远端状态） | 适配器封装下单细节，Bot 负责在纸上/实盘之间切换，smoke 脚本用于手动连通性验证。 |
| 非功能：性能与稳定性（5.1） | `bot.py`, `backtest.py`, `dashboard.py` | `data/`, `data-backtest/` | 通过统一的数据目录与 CSV/JSON 结构，使不同组件可以解耦演进；稳定性由重试逻辑与错误日志保证（详见实现模式章节）。 |
| 非功能：安全性（5.2） | `.env`、`bot.py`, `manual_hyperliquid_smoke.py` | `.env`（未提交）、运行环境 | 所有 API Key/私钥均通过环境变量注入；默认不开启实盘，仅在用户显式配置 Hyperliquid 并运行手工 smoke test 后才启用。 |
| 非功能：可观测性（5.3） | `bot.py`, `dashboard.py`, `replay/` | `data/`, `data-backtest/` | Bot 在 CSV/JSON 中记录完整决策与状态，Dashboard 和 replay 站点负责可视化与回放，支撑「可观测性」需求。 |

> 若后续在 PRD 中新增功能块（例如多账户、多策略调度、告警系统），应在本表中补充行，并在相应代码组件中实现对应的架构支撑。

此外：

- 交易 backend 与 live 模式的配置入口集中在根目录 `.env.example` 与 README 的「Trading Backends & Live Mode Configuration」小节。
- 新增交易所适配器时，统一通过 `exchange_client.py` 中的 `ExchangeClient` 抽象与 `get_exchange_client` 工厂进行扩展，对应 Epic 6 / Story 6.1–6.5 的执行层设计。
