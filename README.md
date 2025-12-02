# Backpack 刷量交易 Bot（基于 DeepSeek）

本项目是一个面向合约量化刷量/做市场景的交易 Bot，支持：

- **Backpack USDC 永续合约刷量 / 做市**（重点）
- 默认使用 DeepSeek，通过任意 OpenAI Chat Completions 兼容接口（由 `LLM_API_BASE_URL` / `LLM_API_KEY` / `LLM_API_TYPE` 配置）进行交易决策
- 支持纸面回测/回放、风险控制、Telegram 通知等

运行方式以 Docker 为主，核心逻辑和配置都已经封装好，你只需要：

1. 注册并开通 Backpack 交易所账号
2. 申请 API Key，并填入 `.env`
3. 配置为 `backpack_futures` 模式
4. 启动 Bot，即可在 Backpack 上进行刷量/交易

---

## 🏢 代部署服务

**不想自己折腾部署、服务器、环境？可以找我代部署。**

- 🖥️ **无需本地电脑 7x24 小时开机**：部署在海外服务器，全天候运行
- 🌍 **网络稳定**：服务器位于海外，访问交易所 API 更稳定
- 🔧 **省心省力**：系统安装、依赖配置、Docker、定时任务、监控等一站式搞定

**费用说明（参考）：**

- 服务器成本：约 40 元/月（按实际服务商为准）
- 代部署服务费：可面议（视你的需求复杂度）
- 大模型 API：我用 GLM 的编程套餐，**第一个月只需要 100 元，API 调用次数基本用不完**。购买地址：<https://www.bigmodel.cn/claude-code?ic=TVUZHTWCW9>

**联系微信：**`gptkit`

> 代部署包含：环境配置、代码部署、配置指导、简单使用说明。如有定制需求（策略改造、风控规则、指标调整等），可另行沟通。

---

## 1. Backpack 注册与准备工作

### 1.1 使用推荐链接注册 Backpack

推荐使用下面的注册链接创建 Backpack 账号（网页打开即可）：

> https://backpack.exchange/join/86324687-8d6e-45f4-a477-7499a8aedd1a

注册完成后：

- 绑定邮箱/手机号，完成基础安全设置
- 按平台要求完成 KYC（如需）
- 开通 USDC 永续合约交易权限

### 1.2 申请 Backpack API Key

在完成账号注册与安全设置后，前往 Backpack 的 API 管理页面：

> https://backpack.exchange/portfolio/settings/api-keys

步骤示例：

1. 登录 Backpack 官网
2. 打开上面的 API Keys 页面
3. 创建新的 API Key
4. 权限建议：
   - 开启 **读取账户 / 读取持仓**
   - 开启 **交易权限（合约下单）**
   - 不建议开启提现权限
5. 创建完成后，你会获得一对 Base64 编码的 ED25519 密钥：
   - 公钥（Public Key）
   - 私钥种子（Secret Seed）

请妥善保管，不要泄露，也不要提交到 Git 仓库。

---

## 2. 环境准备与依赖

### 2.1 基础环境

- 推荐：Ubuntu 等 Linux 云服务器（也可本地 macOS）
- 已安装：
  - Docker 24+（或兼容版本）
  - Git

拉取代码：

```bash
git clone https://github.com/terryso/LLM-trader-test.git
cd LLM-trader-test
```

### 2.2 复制并编辑环境变量文件

项目提供了示例配置：`.env.example`，你可以复制一份：

```bash
cp .env.example .env
```

然后使用你熟悉的编辑器修改 `.env`，重点是 **Backpack 相关配置**。

---

## 3. Backpack 相关配置说明

在 `.env` 文件中，找到并配置以下几个关键变量：

```env
TRADING_BACKEND=backpack_futures

MARKET_DATA_BACKEND=backpack

BACKPACK_API_PUBLIC_KEY=你的_Backpack_API_Public_Key
BACKPACK_API_SECRET_SEED=你的_Backpack_API_Secret_Seed

# 可选：如不填则使用默认官方地址与 5000ms 窗口
#BACKPACK_API_BASE_URL=https://api.backpack.exchange
#BACKPACK_API_WINDOW_MS=5000

# 统一的实盘总开关（建议手动确认后再打开）
LIVE_TRADING_ENABLED=true
```

**说明：**

- `TRADING_BACKEND=backpack_futures`：选择 Backpack 作为交易后端
- `MARKET_DATA_BACKEND=backpack`：选择 Backpack 公共行情 API 作为价格/K 线来源，用于技术指标计算和 Dashboard 展示；在只关心 Backpack 场景下，可以让行情与交易保持一致、完全自洽
- `BACKPACK_API_PUBLIC_KEY` / `BACKPACK_API_SECRET_SEED`：
  - 对应你在 Backpack 后台申请到的 API 公钥/私钥种子
  - 必须是 Base64 编码的 ED25519 密钥（按官方文档生成）
- `LIVE_TRADING_ENABLED=true`：
  - 当且仅当你确认要在 Backpack 上**真实下单/刷量**时再开启
  - 如果不想立刻上实盘测试，可以先不设置或设为 `false`，只跑纸面回测逻辑

除了 Backpack 之外，`.env` 里还需要：

- LLM 相关（推荐直接使用 GLM 的 OpenAI Chat Completions 兼容接口）：
  - `LLM_API_BASE_URL`：你的 LLM 网关地址，例如 `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`
  - `LLM_API_KEY`：在 bigmodel.cn 后台创建的 GLM API Key
  - `LLM_API_TYPE`：接口类型标记，GLM 推荐设置为 `custom`

  **示例：使用 GLM 编程套餐（推荐）**

  ```env
  # LLM 模型配置
  TRADEBOT_LLM_MODEL=glm-4.6
  TRADEBOT_LLM_TEMPERATURE=0.3
  TRADEBOT_LLM_MAX_TOKENS=4000
  #TRADEBOT_LLM_THINKING={"budget_tokens":512}

  # GLM 接口配置
  LLM_API_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4/chat/completions
  LLM_API_KEY=你的_GLM_API_Key
  LLM_API_TYPE=custom
  ```
- 资金风控相关（可选）：
  - `PAPER_START_CAPITAL` / `LIVE_START_CAPITAL`
  - 风险控制开关与每日亏损限制（`RISK_CONTROL_ENABLED`、`DAILY_LOSS_LIMIT_PCT` 等）

- 行情数据来源（可选）：
  - `MARKET_DATA_BACKEND=binance`：从 Binance 现货接口拉取行情（默认）
  - `MARKET_DATA_BACKEND=backpack`：从 Backpack 公共行情 API 获取价格和 K 线，在纯 Backpack 场景下更统一

> 你可以只先配置 Backpack + LLM，其他参数保持默认即可开始试跑。

### Backpack 刷量效果示例（实测）

下图为在 Backpack USDC 永续合约上刷量约 2 天的实测效果：累计成交额约 **20 万 USDC**，整体亏损约 **25 USDC**（主要来自手续费和点差，实际盈亏仍取决于市场波动和具体策略）。

<p align="center">
  <img src="https://i.v2ex.co/pt7yWp6ll.jpeg" alt="Backpack 刷量效果示例" width="520" />
</p>

> 上图仅为历史示例，不代表任何未来收益承诺，请务必结合自身风险偏好谨慎使用。

---

## 4. Backpack 刷量 Bot 启动流程

### 4.1 本地直接运行（不使用 Docker）

推荐在本地开发、调试策略或先小规模试跑时使用本方式。

1. （可选但推荐）创建虚拟环境并安装依赖：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows 使用 .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```

2. 确保项目根目录下已经配置好 `.env` 文件（包括 Backpack、LLM、风控等变量）。

3. 启动 Backpack 刷量 Bot：

   ```bash
   python3 bot.py
   ```

4. 启动监控 Dashboard（可选，与本地 `./data` 目录共用数据）：

   ```bash
   streamlit run dashboard.py
   ```

说明：默认情况下，`bot.py` 和 `dashboard.py` 都会读取项目根目录下的 `.env`，并将运行数据写入 `./data`（可通过 `TRADEBOT_DATA_DIR` 环境变量修改）。

---

### 4.2 构建 Docker 镜像

在项目根目录执行：

```bash
docker build -t tradebot .
```

### 4.3 准备数据目录

```bash
mkdir -p ./data
```

Bot 运行时会把交易记录、AI 决策、持仓状态等信息写入 `./data` 目录，方便后续分析与对账。

### 4.4 启动 Backpack 刷量 Bot（Docker）

确认 `.env` 已正确设置（尤其是 Backpack API 与 LLM），然后：

```bash
docker run --rm -it \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  tradebot
```

此时：

- 如果 `TRADING_BACKEND=backpack_futures` 且 `LIVE_TRADING_ENABLED=true`：
  - Bot 会根据 DeepSeek 的决策，在 Backpack USDC 永续合约上真实下单/刷量
- 如果未开启实盘：
  - 仍然会生成完整的交易决策与日志，但不会向交易所发送真实订单

### 4.5 使用 Docker 启动监控 Dashboard

项目自带一个 Streamlit Dashboard，用于查看 Bot 的表现、收益曲线等：

```bash
docker run --rm -it \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -p 8501:8501 \
  tradebot \
  streamlit run dashboard.py
```

浏览器访问：<http://localhost:8501>

你可以看到：

- 资金曲线、回撤、Sharpe/Sortino 等指标
- 具体每笔交易和 AI 决策内容

---

## 5. Backpack 实盘联通自检（小额测试）

在正式高频刷量前，建议先做一笔非常小金额的联通测试，确认：

- API Key 权限正确
- 延迟/撮合正常
- 账户有足够 USDC 作为保证金

项目提供了一个 Backpack 永续合约的手动 smoke 测试脚本：

```bash
./scripts/run_backpack_futures_smoke.sh \
  --coin BTC \
  --size 0.001 \
  --side long
```

该脚本会：

- 在 `BTC_USDC_PERP` 市场开一笔极小头寸
- 等待几秒
- 再通过 reduce-only 市价单平掉该头寸

如果脚本运行失败，请重点检查：

- `.env` 中 `BACKPACK_API_PUBLIC_KEY` / `BACKPACK_API_SECRET_SEED` 是否正确
- 是否有网络问题/时间窗口配置不正确（`BACKPACK_API_WINDOW_MS`）

---

## 6. 风险控制与 Telegram 通知（可选）

### 6.1 风险控制

在 `.env` 末尾，你可以看到一整段中文风控说明，主要变量包括：

- `RISK_CONTROL_ENABLED`：是否启用风控总开关
- `KILL_SWITCH`：紧急停止新开仓（保留平仓/止损）
- `DAILY_LOSS_LIMIT_ENABLED`：是否启用每日亏损限制
- `DAILY_LOSS_LIMIT_PCT`：每日最大亏损占比（达到后自动拉闸）

建议在实盘刷量前，按自己可承受风险合理调整这些参数。

### 6.2 Telegram 通知

如需用 Telegram 实时接收 Bot 的交易情况，可在 `.env` 配置：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- 可选：`TELEGRAM_SIGNALS_CHAT_ID`（只推送开仓/平仓信号）

配置完成后，每次迭代、开平仓、异常告警等信息都会推送到你的 Telegram。

### 6.3 Runtime Config & /config 命令

运行过程中，如果已经配置好 Telegram 管理员（`.env` 中设置 `TELEGRAM_ADMIN_USER_ID`，值为你的 Telegram user_id），可以通过 `/config` 命令在**不重启 Bot** 的前提下临时调整部分关键配置。

- `/config list`：列出所有支持的运行时配置项及其**当前生效值**（已经包含 runtime overrides 的结果）。
- `/config get KEY`：查看某个配置项的详情，包括当前值和合法取值说明。
- `/config set KEY VALUE`：设置运行时覆盖值（runtime override），仅管理员可用，并会写入审计日志。

当前版本中，**可以通过 `/config` 直接修改的运行时配置项为 3 个**：

- `TRADEBOT_INTERVAL`
  - 含义：交易循环的主时间框架（如 `15m`、`1h`）
  - 合法值：`1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`
  - 生效方式：
    - 通过 `/config set TRADEBOT_INTERVAL 1m` 等命令设置后，**下一轮迭代开始即生效**；
    - 会影响：
      - 主循环 `_run_iteration` 的休眠时间（日志中 `Waiting XXXs...` 的数值）；
      - 计算 Sortino Ratio 时的时间粒度；
      - 构造给 LLM 的 prompt 中的 timeframe 描述，以及用于指标计算的 K 线间隔。
- `TRADEBOT_LLM_TEMPERATURE`
  - 含义：LLM 采样温度
  - 合法范围：`0.0` – `2.0`（超出范围会被拒绝或忽略，沿用 env/default）
  - 生效方式：
    - 通过 `/config set TRADEBOT_LLM_TEMPERATURE 1.2` 等命令设置后，**下一次 LLM 调用立即使用新的温度**；
    - 该值会体现在发送给 LLM 的请求 payload 中，并记录在 `data/ai_messages.csv` 的 metadata.temperature 字段中，方便回溯决策环境。
- `TRADEBOT_LOOP_ENABLED`
  - 含义：主循环总开关（`false` = 暂停 Bot 主循环，只保留 Telegram 等外围线程；`true` = 正常运行）
  - 合法值：`true` / `false`（常见等价写法如 `1`/`0`、`on`/`off` 也会被解析）
  - 生效方式：
    - 当设置为 `false` 时，主循环会跳过交易逻辑，只按 `get_effective_check_interval()` 轮询休眠；
    - 当设置为 `true` 时，主循环恢复正常迭代。

此外，runtime overrides 层本身仍支持对 `TRADING_BACKEND` / `MARKET_DATA_BACKEND` 等 key 进行**进程内覆盖**，但当前实现中：

- 这两个 backend 相关 key 只能通过 `.env` 与重启进程生效；
- `/config` 命令不会接受 `TRADING_BACKEND` / `MARKET_DATA_BACKEND` 作为合法 key，输入时会返回「无效配置项」提示；
- 建议继续使用 `.env` 管理交易/行情后端，避免在运行中试图热切换 backend 导致状态不一致。

权限与风险提示：

- 只有 `TELEGRAM_ADMIN_USER_ID` 对应的管理员账号可以成功执行 `/config set`，普通用户调用会被拒绝并在日志中记录。
- 所有运行时修改都通过 `RuntimeOverrides` 容器保存在内存中，**不会自动写回 `.env`**；一旦进程重启，所有 runtime overrides 会被丢弃，配置会回到 `.env` / 默认值。
- 建议在纸上交易模式或小仓位下先验证 `/config` 行为，再在实盘环境中使用；不要通过过大的 temperature / 过短的 interval 让 LLM 行为过于激进，注意 API 费用与交易风险。

---

## 7. 常见使用场景示例（Backpack 刷量）

- **交易所活动刷量**：
  - 需要在指定永续合约上达到一定成交量
  - 使用本 Bot 持续小额下单+平仓，生成连续成交记录

- **做市/挂单深度**（需视策略微调）：
  - 通过修改系统 Prompt 或策略逻辑，让 Bot 更偏向挂单成交

- **策略研究/回测**：
  - 先在纯纸面模式下调参
  - 再切换到 Backpack 实盘进行小额验证

> 如果你有更复杂的刷量/做市需求（如双边对敲、多账号协同、细粒度手续费/返佣优化等），可以在微信沟通定制开发。

---

## 8. 免责声明

本仓库及相关代码仅用于技术研究和教育演示：

- 不构成任何投资建议或交易建议
- 不保证任何收益或回报
- 使用本项目产生的任何直接或间接损失，均由使用者自行承担

在你开始实盘刷量或交易之前，请务必：

- 充分理解永续合约、高杠杆交易的风险
- 先在纸面/小额资金环境中长期验证
- 仔细评估自己的风险承受能力

---

## 9. 开发者说明（简要）

- 使用 Docker 运行时，日志与数据统一写入 `/app/data`（映射到本地 `./data`）
- 不会自动覆盖已有数据文件，如需迁移旧数据请手工处理
- 项目包含完整的单元测试与回测脚本，适合二次开发和策略研究

如果你只关心 Backpack 刷量，把注意力放在：

- `.env` 中 Backpack 与风险控制相关变量
- `scripts/manual_backpack_futures_smoke.py` 联通测试脚本
- Docker 启动命令

即可完成从 0 到 1 的搭建与上线。
