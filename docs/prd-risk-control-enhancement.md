# 风控系统增强 - 产品需求文档

**Author:** Nick  
**Date:** 2025-11-30  
**Version:** 1.0  
**Status:** Draft

---

## Executive Summary

为 DeepSeek Paper Trading Bot 增加系统级风险控制能力，包括 **Kill-Switch（紧急停止）** 和 **每日亏损限制** 两个核心功能。这些功能旨在为实盘交易提供安全底线，防止因系统异常、市场剧烈波动或策略失效导致的重大损失。

### 产品定位

本功能是对现有交易系统的**安全增强**，属于 Roadmap Tier 2（Emergency Controls & Monitoring）的核心组成部分。

### 核心价值

- **资金保护**：在异常情况下快速止损，保护账户资金
- **心理安全**：用户可以放心让 Bot 长时间运行，知道有安全网兜底
- **合规基础**：为未来更复杂的风控规则奠定架构基础

---

## 项目分类

**技术类型:** cli_tool / trading_bot  
**领域:** fintech  
**复杂度:** medium

本功能涉及：
- 状态管理（风控状态持久化）
- 外部集成（Telegram 命令）
- 实时监控（权益变化追踪）

---

## 成功标准

### 功能验收标准

1. **Kill-Switch 有效性**
   - 触发 Kill-Switch 后，Bot 在下一个迭代周期内停止所有新开仓操作
   - 现有持仓的 SL/TP 检查继续正常工作
   - Kill-Switch 状态在 Bot 重启后保持

2. **每日亏损限制有效性**
   - 当日权益下降达到阈值时，自动触发交易暂停
   - 暂停状态通过 Telegram 及时通知用户
   - 次日自动重置每日亏损计数器

3. **恢复机制可靠性**
   - Telegram 命令可以成功解除 Kill-Switch
   - 恢复操作为单步命令 `/resume`，并受每日亏损限制等风控策略保护，防止误操作
   - 所有状态变更有完整日志记录

### 非功能验收标准

- 风控检查不显著增加每次迭代的执行时间（< 100ms）
- 风控状态持久化不影响现有 CSV/JSON 文件结构
- 新增环境变量有合理默认值，不破坏现有部署

---

## 产品范围

### MVP - 最小可行产品

#### Kill-Switch（紧急停止）

| 功能点 | 描述 |
|--------|------|
| 环境变量控制 | `KILL_SWITCH=true` 立即暂停新开仓 |
| Telegram 命令触发 | `/kill` 命令触发 Kill-Switch |
| Telegram 命令恢复 | `/resume` 命令在 Kill-Switch 激活且未被每日亏损限制阻挡时直接解除 Kill-Switch（兼容旧的 `/resume confirm` 作为别名输入） |
| 状态持久化 | Kill-Switch 状态保存到 `portfolio_state.json` |
| 状态通知 | 触发/解除时发送 Telegram 通知 |
| 行为定义 | 仅暂停新开仓，保留现有持仓，SL/TP 检查继续 |

#### 每日亏损限制

| 功能点 | 描述 |
|--------|------|
| 阈值配置 | `DAILY_LOSS_LIMIT_PCT=5.0` 表示 -5% 触发暂停 |
| 计算方式 | 基于当日起始权益与当前权益的变化百分比 |
| 自动触发 | 达到阈值自动激活 Kill-Switch |
| 通知机制 | 触发时发送详细 Telegram 通知（当前亏损、阈值、建议） |
| 每日重置 | UTC 00:00 自动重置每日起始权益基准 |
| 手动重置 | `/reset_daily` 命令手动重置当日基准 |

### Growth Features（后续迭代）

- **分级告警**：在达到 50%、75%、90% 阈值时发送预警
- **滑点追踪**：记录实际成交价与预期价差
- **最大持仓限制**：限制同时持仓数量
- **相关性检查**：避免同向持有高度相关资产

### Vision（远期愿景）

- **Web 控制面板**：通过仪表盘管理风控设置
- **智能风控**：基于市场波动率动态调整阈值
- **多账户风控**：跨账户统一风险管理

---

## 功能需求

### 风控状态管理

- **FR1**: 系统维护一个全局风控状态（RiskControlState），包含 Kill-Switch 状态、每日亏损状态、触发时间等信息
- **FR2**: 风控状态在每次迭代开始时加载，迭代结束时保存
- **FR3**: 风控状态持久化到 `portfolio_state.json` 的 `risk_control` 字段
- **FR4**: Bot 启动时检查并恢复上次的风控状态

### Kill-Switch 功能

- **FR5**: 用户可以通过设置环境变量 `KILL_SWITCH=true` 启用 Kill-Switch
- **FR6**: 用户可以通过 Telegram 发送 `/kill` 命令触发 Kill-Switch
- **FR7**: Kill-Switch 激活后，系统拒绝所有 `signal=entry` 的 LLM 决策
- **FR8**: Kill-Switch 激活后，系统继续执行 `signal=close` 和 SL/TP 检查
- **FR9**: 用户可以通过 Telegram 发送 `/resume` 命令解除 Kill-Switch
- **FR10**: `/resume` 命令在 Kill-Switch 激活且未被每日亏损限制阻挡时直接解除 Kill-Switch，系统仍兼容旧版 `/resume confirm` 形式作为等价输入
- **FR11**: Kill-Switch 状态变更时，系统发送 Telegram 通知

### 每日亏损限制功能

- **FR12**: 用户可以通过环境变量 `DAILY_LOSS_LIMIT_PCT` 配置每日最大亏损百分比
- **FR13**: 系统在每次迭代时计算当日权益变化百分比
- **FR14**: 当日亏损达到阈值时，系统自动激活 Kill-Switch
- **FR15**: 系统记录每日起始权益作为计算基准
- **FR16**: 系统在 UTC 00:00 自动重置每日起始权益基准
- **FR17**: 用户可以通过 Telegram 发送 `/reset_daily` 命令手动重置当日基准
- **FR18**: 每日亏损触发暂停时，系统发送包含详细信息的 Telegram 通知

### 日志与审计

- **FR19**: 所有风控状态变更记录到日志文件
- **FR20**: 风控事件记录到 `ai_decisions.csv`（action 类型为 `RISK_CONTROL`）
- **FR21**: 用户可以通过 Telegram 发送 `/status` 命令查看当前风控状态

### Telegram 命令集成

- **FR22**: 系统支持通过 Telegram Webhook 或轮询接收用户命令
- **FR23**: 系统仅响应来自 `TELEGRAM_CHAT_ID` 的命令（安全校验）
- **FR24**: 未知命令返回帮助信息，列出可用命令

---

## 非功能需求

### 性能

- **NFR1**: 风控状态检查在每次迭代中增加的延迟 < 100ms
- **NFR2**: Telegram 命令响应时间 < 3 秒

### 可靠性

- **NFR3**: 风控状态持久化使用原子写入，防止数据损坏
- **NFR4**: 网络故障不影响本地风控逻辑执行

### 安全性

- **NFR5**: Telegram 命令仅接受来自配置的 Chat ID
- **NFR6**: 敏感操作（如 `/resume`）应受风险控制策略约束（例如每日亏损限制阻挡恢复），防止误操作

### 可观测性

- **NFR7**: 风控状态变更有完整的日志记录
- **NFR8**: 仪表盘显示当前风控状态

### 兼容性

- **NFR9**: 新增环境变量有合理默认值，不破坏现有部署
- **NFR10**: 风控功能可通过配置完全禁用

---

## 技术设计要点

### 数据结构

```python
@dataclass
class RiskControlState:
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_triggered_at: Optional[datetime] = None
    
    daily_start_equity: Optional[float] = None
    daily_start_date: Optional[str] = None  # YYYY-MM-DD
    daily_loss_pct: float = 0.0
    daily_loss_triggered: bool = False
```

### 环境变量

| 变量名 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `KILL_SWITCH` | bool | `false` | 启动时是否激活 Kill-Switch |
| `DAILY_LOSS_LIMIT_PCT` | float | `5.0` | 每日最大亏损百分比 |
| `DAILY_LOSS_LIMIT_ENABLED` | bool | `true` | 是否启用每日亏损限制 |
| `RISK_CONTROL_ENABLED` | bool | `true` | 是否启用风控系统 |

### Telegram 命令

| 命令 | 描述 | 示例 |
|------|------|------|
| `/kill` | 触发 Kill-Switch | `/kill` |
| `/resume` | 解除 Kill-Switch（单步命令，兼容旧的 `/resume confirm` 形式） | `/resume` |
| `/status` | 查看风控状态 | `/status` |
| `/reset_daily` | 重置每日亏损基准 | `/reset_daily` |
| `/help` | 显示帮助信息 | `/help` |

#### `/balance` 实盘账户视角（已实现）

- **目标**：当 `TRADING_BACKEND` 为 `binance_futures` 或 `backpack_futures` 且开启实盘时，`/balance` 展示 *真实交易所账户快照*，而不是仅依赖 `portfolio_state.json` 中的本地组合视图。
- **Binance Futures 方案**：
  - 复用现有 `get_binance_client()`，在 Bot 层调用 `Client.futures_account()` 获取账户信息（如 `totalWalletBalance`、`totalMarginBalance`、`positions` 等）。
  - 在 Bot 层整理为统一的 snapshot 结构，例如：`balance`（钱包余额 / 可用资金）、`total_equity`（总权益）、`total_margin`（已用保证金汇总）、`positions_count`（持仓合约数量）。
  - 通过 Telegram 命令 handler 工厂（如 `create_kill_resume_handlers`）注入 `account_snapshot_fn` 到 `/balance` handler，使 handler 本身保持“只关心 snapshot 字段”的视图，不直接依赖具体交易所 SDK。
- **Backpack Futures 方案**：
  - 在 `BackpackFuturesExchangeClient` 中新增 `get_account_snapshot()` 方法，调用 Backpack 官方 API：
    - `collateralQuery` (`GET /api/v1/capital/collateral`)：获取 `netEquity`、`netEquityAvailable`、`netEquityLocked`、`pnlUnrealized`
    - `positionQuery` (`GET /api/v1/futures/position`)：获取持仓列表并统计有效持仓数量
  - 返回的数据结构与 Binance 的 snapshot 对齐：`balance`、`total_equity`、`total_margin`、`positions_count`，方便 Telegram 层复用同一渲染逻辑。
- **回退策略**：
  - 当未启用上述实盘 backend，或交易所账户接口暂不可用 / 返回错误时，`/balance` 回退使用当前基于 `portfolio_state.json` 的组合视图，不影响现有回测和 Paper Trading 行为。

### 集成点

1. **主循环集成**：在 `_run_iteration()` 开始时检查风控状态
2. **决策处理集成**：在 `process_ai_decisions()` 中过滤被禁止的信号
3. **状态持久化集成**：在 `save_state()` 中保存风控状态
4. **Telegram 集成**：扩展现有 Telegram 模块支持命令接收

---

## 实现建议

### 模块结构

```
core/
├── risk_control.py      # 风控状态管理和检查逻辑
├── state.py             # 扩展现有状态管理

notifications/
├── telegram.py          # 扩展支持命令接收
├── telegram_commands.py # 新增：命令处理器
```

### 实现顺序

1. **Phase 1**: 实现 `RiskControlState` 数据结构和持久化
2. **Phase 2**: 实现 Kill-Switch 环境变量控制
3. **Phase 3**: 实现每日亏损限制计算和触发
4. **Phase 4**: 实现 Telegram 命令接收和处理
5. **Phase 5**: 集成测试和文档更新

---

## 验收测试场景

### Kill-Switch 测试

| 场景 | 预期结果 |
|------|----------|
| 设置 `KILL_SWITCH=true` 启动 Bot | Bot 启动后不执行任何新开仓 |
| 发送 `/kill` 命令 | Kill-Switch 激活，收到确认通知 |
| Kill-Switch 激活时 LLM 返回 entry 信号 | 信号被忽略，记录日志 |
| Kill-Switch 激活时 LLM 返回 close 信号 | 信号正常执行 |
| Kill-Switch 激活时触发 SL/TP | SL/TP 正常执行 |
| 发送 `/resume` 命令 | Kill-Switch 解除，收到确认通知（若未被每日亏损限制阻挡；旧版 `/resume confirm` 仍作为等价输入被接受） |

### 每日亏损限制测试

| 场景 | 预期结果 |
|------|----------|
| 当日亏损达到阈值 | 自动激活 Kill-Switch，发送通知 |
| UTC 00:00 跨日 | 每日基准自动重置 |
| 发送 `/reset_daily` 命令 | 每日基准重置为当前权益 |
| 查询 `/status` | 显示当前亏损百分比和阈值 |

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Telegram API 不可用 | 无法远程控制 | 环境变量作为备用控制方式 |
| 状态文件损坏 | 风控状态丢失 | 原子写入 + 备份文件 |
| 误触发 Kill-Switch | 错过交易机会 | `/resume` 恢复机制 |
| 时区问题导致每日重置异常 | 计算错误 | 统一使用 UTC 时间 |

---

## 附录

### A. 相关文档

- [现有 PRD](./prd.md)
- [架构文档](./architecture/)
- [Epic 分解](./epics.md)

### B. 参考实现

- Binance 风控 API
- 3Commas 风险管理功能
- TradingView 告警系统

---

_本 PRD 定义了 DeepSeek Paper Trading Bot 风控系统增强的完整需求，为实盘交易提供安全保障。_

_Created: 2025-11-30 by Nick with AI facilitator (PM John)_
