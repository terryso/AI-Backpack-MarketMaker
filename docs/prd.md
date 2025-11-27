# DeepSeek Paper Trading Bot 产品需求文档（反向工程草稿）

> 本 PRD 基于现有代码和 README 反向整理，目标是帮助理解当前能力边界，并为后续扩展提供统一的产品视角。

## 1. 产品概述

### 1.1 简介

DeepSeek Paper Trading Bot 是一个 **多资产加密货币交易机器人**，结合：

- 多时间框架技术分析（15m / 1h / 4h）
- LLM（DeepSeek）决策
- 本地风险控制与资金管理
- 纸上交易 + 可选 Hyperliquid 实盘
- 回测与可视化仪表盘

### 1.2 产品定位

- **类型**：教育 / 实验性开源项目
- **目标用户**：
  - 有一定编程基础的量化/加密交易爱好者
  - 想研究「LLM + 交易策略」的工程师/研究者
- **核心价值**：
  - 提供一套完整的、可运行的「LLM 驱动交易系统」样板
  - 将策略逻辑、LLM 提示词、风控约束与执行链路整合在一起，便于二次开发

### 1.3 使用假设

- 用户能自行获取 Binance API Key 与 LLM API Key（OpenRouter）。
- 用户具备基础 Docker / Python 环境知识。
- 用户愿意自己为任何实盘风险负责（仓位大小、杠杆等完全由用户配置）。

## 2. 目标与非目标

### 2.1 产品目标

1. **安全的实验环境**：
   - 默认使用纸上交易，避免直接触达真实资金。
2. **可解释的 LLM 决策流程**：
   - 所有 AI 决策写入 CSV，并可在仪表盘和回放站点中重现。
3. **多时间框架策略样板**：
   - 将 4H 趋势、1H 结构与 15m 执行层组合成一套清晰的逻辑。
4. **可插拔的 Prompt 与 LLM**：
   - 通过环境变量 / Prompt 文件轻松替换策略制定规则与 LLM 模型。
5. **易于扩展的工程结构**：
   - 清晰拆分 Bot、回测、仪表盘与实盘适配层，便于新增资产或策略。

### 2.2 非目标

- 不提供任何「盈利保证」「信号服务」或投资建议。
- 不承诺满足严格的合规、安全、审计要求（面向个人/小团队实验）。
- 非多资产组合管理系统（主要场景仍然是单账户、多资产的策略实验）。

## 3. 用户与场景

### 3.1 主要用户角色

1. **个人交易者 / 量化爱好者**：
   - 希望在纸上环境中迭代 LLM 策略与 Prompt。
   - 可能偶尔启用小额 Hyperliquid 实盘做验证。
2. **LLM 研究者 / 工程师**：
   - 关注「Prompt 设计 → LLM 输出 → 风控校验 → 决策执行」的完整闭环。
   - 希望有真实系统可做实验，而非纯理论推演。

### 3.2 场景示例

- 在本地或服务器上长期运行 Bot，使用 Telegram 接收每轮迭代摘要和进出场信号。
- 使用 `backtest.py` 在固定时间区间内评估不同 Prompt/LLM 配置对收益与风险的影响。
- 使用 Streamlit 仪表盘对比组合净值曲线和 BTC Buy&Hold 的表现差异。

## 4. 核心功能需求

### 4.1 交易主循环（Bot）

1. **调度与时间框架**：
   - 默认每 15 分钟运行一次主循环（可通过环境变量调整）。
2. **行情拉取**：
   - 通过 Binance API 为多个交易对（如 ETHUSDT、SOLUSDT 等）拉取：
     - 200 条 15m K 线
     - 100 条 1h K 线
     - 100 条 4h K 线
3. **指标计算**：
   - 对每个时间框架计算：
     - EMA：20 / 50 / 200
     - RSI14
     - MACD（12, 26, 9）
     - ATR 与成交量等其他信号
4. **Prompt 构建**：
   - 将多周期行情、指标、当前仓位与风险参数组织成分层结构，拼接到系统 Prompt 中。
5. **LLM 调用**：
   - 通过 OpenRouter 调用 DeepSeek 模型（默认：`deepseek/deepseek-chat-v3.1`）。
6. **决策解析与校验**：
   - 要求 LLM 严格返回 JSON：
     - `signal`（entry/close/hold）
     - `side`（long/short）
     - `quantity`、`profit_target`、`stop_loss`、`leverage`、`confidence`、`risk_usd`、`justification` 等
   - Bot 校验：
     - JSON 结构与字段是否完整
     - 数值是否在合理区间（例如风险不超过 1–2%）。
     - 不合法则拒绝执行并记录错误。
7. **执行与仓位管理**：
   - 纸上交易：更新本地 `positions`、`balance`、`equity_history` 等。
   - 实盘模式：调用 Hyperliquid 客户端下单，并附带 SL/TP 触发单。

### 4.2 风险控制与资金管理

1. **单笔风险限制**：
   - 目标：每笔交易的最大损失控制在账户总资金 1–2% 区间。
2. **强制止损与止盈**：
   - 所有 ENTRY 交易必须提供 `stop_loss`；没有止损的建议视为无效。
   - 根据 ATR、结构位和 4H 趋势计算合理的止损距离与目标位。
3. **交易类型与风险分级**：
   - Type A：顺势（With-trend），风险约 2%。
   - Type B：逆势（Counter-trend），风险约 1%。
   - Type C：震荡（Range），风险约 1%。
4. **退出规则**：
   - 止损/止盈命中；
   - 1H 结构被突破；
   - 4H 趋势发生反转；
   - 禁止仅因价格接近止损（例如 20% 距离内）而人工提早平仓。

### 4.3 LLM 配置与 Prompt 管理

1. **系统 Prompt 来源**：
   - 优先级：
     1. `TRADEBOT_SYSTEM_PROMPT_FILE` 指向的文件内容
     2. 环境变量 `TRADEBOT_SYSTEM_PROMPT`
     3. 内置默认规则（`DEFAULT_TRADING_RULES_PROMPT`）
2. **模型与采样参数**：
   - 通过环境变量控制：
     - `TRADEBOT_LLM_MODEL`（默认 DeepSeek）
     - `TRADEBOT_LLM_TEMPERATURE`
     - `TRADEBOT_LLM_MAX_TOKENS`
     - `TRADEBOT_LLM_THINKING`（可为数值、JSON 或文本）
3. **Backtest/Live 隔离**：
   - `backtest.py` 使用单独的环境变量前缀（`BACKTEST_*`）覆盖 LLM 参数，而不影响线上。

### 4.4 数据持久化与日志

1. **数据目录**：
   - 默认 `data/`；可通过 `TRADEBOT_DATA_DIR` 重定向。
2. **关键文件**：
   - `portfolio_state.csv` / `portfolio_state.json`：账户状态与权益曲线。
   - `trade_history.csv`：交易历史（ENTRY / CLOSE）。
   - `ai_decisions.csv`：LLM 决策摘要。
   - `ai_messages.csv`：完整对话 / 提示内容。
3. **Schema 约束**：
   - `bot.py` 在初始化时确保 CSV 列结构完整，必要时自动迁移旧文件的列。

### 4.5 仪表盘（Dashboard）

1. **数据源**：
   - 读取 `data/portfolio_state.csv`、`trade_history.csv`、`ai_decisions.csv`、`ai_messages.csv`。
2. **核心视图**：
   - 组合净值曲线 + BTC Buy&Hold 基准对比。
   - 关键指标：Total Return、Sharpe、Sortino、Realized / Unrealized PnL、Margin 等。
   - 持仓列表、订单细节、一览。
3. **交互性**：
   - 可通过时间范围筛选、图表缩放等方式探索数据。

### 4.6 回测（Backtest）

1. **回测配置**：
   - 通过环境变量配置起止时间、间隔、LLM 模型与 Prompt 覆盖等。
2. **数据获取与缓存**：
   - 使用 Binance kline 接口 + `data-backtest/cache/` 做本地缓存。
3. **执行逻辑**：
   - 构建 `HistoricalBinanceClient`，重用 `bot` 的逻辑评估历史每一根 bar。
4. **输出**：
   - 每个回测 run 输出到独立目录 `data-backtest/run-<id>/`，包含组合状态、交易、AI 决策和结果 JSON。

### 4.7 Telegram 通知

1. **迭代通知**：
   - 当设置 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 时，每次主循环结束推送组合摘要与错误信息。
2. **信号频道**：
   - `TELEGRAM_SIGNALS_CHAT_ID` 单独用于 ENTRY/CLOSE 信号，内容包括方向、杠杆、风险、R/R、PNL 等。

### 4.8 Hyperliquid 实盘集成

1. **开启条件**：
   - `HYPERLIQUID_LIVE_TRADING=true` 且配置钱包地址与私钥：
     - `HYPERLIQUID_WALLET_ADDRESS`
     - `HYPERLIQUID_PRIVATE_KEY`
2. **行为**：
   - 使用 Hyperliquid SDK 初始化账户与连接。
   - 根据 tick size 正规化价格，使用 IOC/GTC 下单，并自动挂 SL/TP 触发单。
   - 若初始化失败则退回纸上交易，并记录错误日志。
   - 具体环境变量与 backend 选择语义，详见：根目录 `.env.example` 以及 README 中的「Trading Backends & Live Mode Configuration」小节。

## 5. 非功能需求

### 5.1 性能与稳定性

- 能够长时间持续运行（以 15m 周期为主），在 API 错误或网络抖动时通过重试与错误日志维持服务。
- 回测在合理时间内完成典型一周~数周的历史评估。

### 5.2 安全性

- 私钥、API Key 均通过 `.env` 注入，避免写入代码库。
- 默认不开启实盘交易，只有显式配置后才启用 Hyperliquid Live。

### 5.3 可观测性

- 所有关键操作（行情拉取、LLM 调用、下单、异常）需记录到日志。
- 交易与状态变更必须可从 CSV/JSON 中复现（为回放与审计提供基础）。

## 6. 开放问题与后续路线（对应 README 路线图）

基于 README 的 Tier Roadmap，后续潜在方向包括：

- 更完备的 Hyperliquid 实盘功能与应急控制（Kill-Switch、滑点跟踪等）。
- 更智能的仓位规模管理与组合级风险约束。
- 多 LLM 策略与投票系统。
- 更丰富的回测能力（多窗口、多参数测试、蒙特卡洛等）。
- 高阶表现分析与智能预警 / 报告系统。

本 PRD 只描述当前仓库已体现或明显规划中的能力，为进一步规划可在此基础上细化分阶段目标与用户故事。

## 7. 验收标准（草案）

### 7.1 运行与稳定性

- 在典型配置下，Bot 以 15m 频率连续运行 ≥ 24 小时，无未捕获异常导致主循环退出。
- 当出现 Binance 或网络错误时，记录清晰的错误日志，并在下一轮迭代自动重试，而不是直接终止进程。

### 7.2 交易与风控行为

- 当未开启 `HYPERLIQUID_LIVE_TRADING` 时，不向 Hyperliquid 发送任何实盘订单。
- 每一笔 ENTRY / CLOSE 在 `trade_history.csv` 中都有完整记录（至少包含方向、数量、价格、SL/TP 与时间戳等关键字段）。
- 所有 ENTRY 决策均带有合法 `stop_loss`，对应的最大亏损不超过账户资金的约 1–2%。

### 7.3 数据与可观测性

- 每一轮主循环至少产生一条 `ai_decisions.csv` 记录，可通过 `ai_messages.csv` 还原对应 Prompt 与模型回复。
- 在不修改 `trade_history.csv` 的前提下运行 `scripts/recalculate_portfolio.py`，生成的 `portfolio_state.json` 与实际账户状态在允许误差范围内一致。
- Dashboard 能成功加载 `data/` 目录下的 CSV 文件，并展示净值曲线、Sharpe、Sortino 等核心指标。

### 7.4 回测与模式隔离

- 执行一次典型回测后，在 `data-backtest/run-<id>/` 目录中可以找到组合状态、交易记录、AI 决策 CSV 以及结果 JSON。
- 回测运行不会修改 live 模式下 `data/` 目录中的文件（除非用户显式选择使用相同目录）。
