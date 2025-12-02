# 风控系统增强 - Epic 与 Story 分解

**Author:** Nick  
**Date:** 2025-11-30  
**PRD Reference:** [prd-risk-control-enhancement.md](./prd-risk-control-enhancement.md)

---

## Epic 概览

| Epic | 名称 | Story 数量 | 依赖 |
|------|------|------------|------|
| Epic 7.1 | 风控状态管理基础设施 | 4 | 无 |
| Epic 7.2 | Kill-Switch 核心功能 | 5 | Epic 7.1 |
| Epic 7.3 | 每日亏损限制功能 | 4 | Epic 7.1 |
| Epic 7.4 | Telegram 命令集成 | 5 | Epic 7.2, 7.3 |

> 注：Epic 编号延续现有 `epics.md` 中的 Epic 6，使用 7.x 系列。

---

## Epic 7.1: 风控状态管理基础设施

### Epic 概述

**目标**: 建立风控系统的数据结构、状态管理和持久化基础设施。

**范围**:
- 定义 `RiskControlState` 数据结构
- 实现状态持久化到 `portfolio_state.json`
- 实现状态加载和初始化逻辑
- 添加风控相关环境变量

**验收标准**:
- 风控状态可以正确保存和加载
- Bot 重启后风控状态保持不变
- 新增环境变量有合理默认值

---

### Story 7.1.1: 定义 RiskControlState 数据结构

**As a** developer  
**I want** a well-defined data structure for risk control state  
**So that** all risk control features have a consistent state model

**Acceptance Criteria**:
- [ ] 创建 `core/risk_control.py` 模块
- [ ] 定义 `RiskControlState` dataclass，包含：
  - `kill_switch_active: bool`
  - `kill_switch_reason: Optional[str]`
  - `kill_switch_triggered_at: Optional[datetime]`
  - `daily_start_equity: Optional[float]`
  - `daily_start_date: Optional[str]`
  - `daily_loss_pct: float`
  - `daily_loss_triggered: bool`
- [ ] 实现 `to_dict()` 和 `from_dict()` 方法用于序列化
- [ ] 添加单元测试

**Technical Notes**:
```python
@dataclass
class RiskControlState:
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_triggered_at: Optional[datetime] = None
    daily_start_equity: Optional[float] = None
    daily_start_date: Optional[str] = None
    daily_loss_pct: float = 0.0
    daily_loss_triggered: bool = False
```

---

### Story 7.1.2: 添加风控相关环境变量

**As a** user  
**I want** to configure risk control via environment variables  
**So that** I can customize risk limits without changing code

**Acceptance Criteria**:
- [ ] 在 `config/settings.py` 中添加以下配置：
  - `RISK_CONTROL_ENABLED` (default: `true`)
  - `KILL_SWITCH` (default: `false`)
  - `DAILY_LOSS_LIMIT_ENABLED` (default: `true`)
  - `DAILY_LOSS_LIMIT_PCT` (default: `5.0`)
- [ ] 更新 `.env.example` 添加新变量说明
- [ ] 添加配置验证（如百分比范围检查）
- [ ] 添加单元测试

**Technical Notes**:
```python
RISK_CONTROL_ENABLED = os.getenv("RISK_CONTROL_ENABLED", "true").lower() in ("true", "1", "yes")
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() in ("true", "1", "yes")
DAILY_LOSS_LIMIT_ENABLED = os.getenv("DAILY_LOSS_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "5.0"))
```

---

### Story 7.1.3: 实现风控状态持久化

**As a** system  
**I want** risk control state to persist across restarts  
**So that** risk limits remain enforced even after bot restarts

**Acceptance Criteria**:
- [ ] 扩展 `save_state_to_json()` 保存 `risk_control` 字段
- [ ] 扩展 `load_state_from_json()` 加载 `risk_control` 字段
- [ ] 处理旧版本 JSON 文件（无 `risk_control` 字段）的兼容性
- [ ] 使用原子写入防止数据损坏
- [ ] 添加单元测试

**Technical Notes**:
- 在 `portfolio_state.json` 中添加 `risk_control` 顶级字段
- 加载时如果字段不存在，使用默认值初始化

---

### Story 7.1.4: 集成风控状态到主循环

**As a** system  
**I want** risk control state to be checked on every iteration  
**So that** risk limits are enforced in real-time

**Acceptance Criteria**:
- [ ] 在 `bot.py` 中添加全局 `risk_control_state` 变量
- [ ] 在 `load_state()` 中加载风控状态
- [ ] 在 `save_state()` 中保存风控状态
- [ ] 在 `_run_iteration()` 开始时调用风控检查函数
- [ ] 添加集成测试

**Technical Notes**:
```python
# bot.py
from core.risk_control import RiskControlState, check_risk_limits

risk_control_state = RiskControlState()

def _run_iteration():
    # 风控检查
    if RISK_CONTROL_ENABLED:
        check_risk_limits(risk_control_state, ...)
    # ... 现有逻辑
```

---

## Epic 7.2: Kill-Switch 核心功能

### Epic 概述

**目标**: 实现 Kill-Switch 紧急停止功能，允许用户快速暂停所有新开仓操作。

**范围**:
- 环境变量触发 Kill-Switch
- Kill-Switch 状态检查和执行
- 信号过滤逻辑
- 状态变更通知

**验收标准**:
- Kill-Switch 激活后，所有 entry 信号被拒绝
- close 信号和 SL/TP 检查继续正常工作
- 状态变更有 Telegram 通知

**依赖**: Epic 7.1

---

### Story 7.2.1: 实现 Kill-Switch 激活逻辑

**As a** user  
**I want** to activate Kill-Switch via environment variable  
**So that** I can immediately stop new trades when needed

**Acceptance Criteria**:
- [ ] 在 `core/risk_control.py` 中实现 `activate_kill_switch(state, reason)` 函数
- [ ] 函数设置 `kill_switch_active=True`、`reason` 和 `triggered_at`
- [ ] Bot 启动时检查 `KILL_SWITCH` 环境变量
- [ ] 如果 `KILL_SWITCH=true`，自动激活 Kill-Switch
- [ ] 添加单元测试

**Technical Notes**:
```python
def activate_kill_switch(state: RiskControlState, reason: str) -> None:
    state.kill_switch_active = True
    state.kill_switch_reason = reason
    state.kill_switch_triggered_at = datetime.now(timezone.utc)
```

---

### Story 7.2.2: 实现 Kill-Switch 解除逻辑

**As a** user  
**I want** to deactivate Kill-Switch  
**So that** I can resume normal trading after resolving issues

**Acceptance Criteria**:
- [ ] 实现 `deactivate_kill_switch(state)` 函数
- [ ] 函数重置 `kill_switch_active=False` 和相关字段
- [ ] 保留 `daily_loss_triggered` 状态（如果是每日亏损触发的）
- [ ] 添加单元测试

**Technical Notes**:
```python
def deactivate_kill_switch(state: RiskControlState, force: bool = False) -> bool:
    if state.daily_loss_triggered and not force:
        return False  # 每日亏损触发的需要 force=True 或等待次日重置
    state.kill_switch_active = False
    state.kill_switch_reason = None
    state.kill_switch_triggered_at = None
    return True
```

---

### Story 7.2.3: 实现信号过滤逻辑

**As a** system  
**I want** to filter entry signals when Kill-Switch is active  
**So that** no new positions are opened during risk events

**Acceptance Criteria**:
- [ ] 在 `process_ai_decisions()` 中添加 Kill-Switch 检查
- [ ] 当 Kill-Switch 激活时，跳过所有 `signal=entry` 的决策
- [ ] 记录被跳过的信号到日志和 `ai_decisions.csv`
- [ ] `signal=close` 和 `signal=hold` 正常处理
- [ ] 添加单元测试

**Technical Notes**:
```python
def process_ai_decisions(decisions: Dict[str, Any]) -> None:
    for coin, decision in decisions.items():
        signal = decision.get("signal", "hold")
        
        # Kill-Switch 检查
        if signal == "entry" and risk_control_state.kill_switch_active:
            logging.warning("Kill-Switch active: skipping entry for %s", coin)
            log_ai_decision(coin, "BLOCKED", "Kill-Switch active", 0)
            continue
        
        # ... 现有逻辑
```

---

### Story 7.2.4: 确保 SL/TP 在 Kill-Switch 期间正常工作

**As a** user  
**I want** stop-loss and take-profit to work during Kill-Switch  
**So that** existing positions are still protected

**Acceptance Criteria**:
- [ ] 验证 `check_stop_loss_take_profit()` 不受 Kill-Switch 影响
- [ ] 验证 `execute_close()` 在 Kill-Switch 期间正常工作
- [ ] 添加集成测试验证此行为
- [ ] 在文档中明确说明此行为

**Technical Notes**:
- 此 Story 主要是验证和测试，确保现有逻辑不被 Kill-Switch 影响
- `check_stop_loss_take_profit()` 调用 `execute_close()`，不涉及 entry 信号

---

### Story 7.2.5: 实现 Kill-Switch 状态变更通知

**As a** user  
**I want** to receive Telegram notifications when Kill-Switch status changes  
**So that** I'm aware of risk control events

**Acceptance Criteria**:
- [ ] Kill-Switch 激活时发送通知，包含：
  - 触发原因
  - 触发时间
  - 当前持仓数量
  - 恢复指令提示
- [ ] Kill-Switch 解除时发送确认通知
- [ ] 通知使用 Markdown 格式，清晰易读
- [ ] 添加单元测试

**Technical Notes**:
```python
def notify_kill_switch_activated(reason: str, positions_count: int) -> None:
    message = f"""🚨 *Kill-Switch 已激活*

*原因:* {reason}
*时间:* {datetime.now(timezone.utc).isoformat()}
*当前持仓:* {positions_count} 个

⚠️ 所有新开仓已暂停
✅ 现有持仓 SL/TP 继续生效

恢复交易: 发送 `/resume`"""
    send_telegram_message(message)
```

---

## Epic 7.3: 每日亏损限制功能

### Epic 概述

**目标**: 实现每日亏损限制功能，当日亏损达到阈值时自动暂停交易。

**范围**:
- 每日起始权益记录
- 实时亏损百分比计算
- 阈值触发逻辑
- 每日自动重置

**验收标准**:
- 当日亏损达到阈值时自动激活 Kill-Switch
- UTC 00:00 自动重置每日基准
- 触发时发送详细通知

**依赖**: Epic 7.1

---

### Story 7.3.1: 实现每日起始权益记录

**As a** system  
**I want** to record daily starting equity  
**So that** daily loss can be calculated accurately

**Acceptance Criteria**:
- [ ] 在 `_run_iteration()` 开始时检查是否需要记录每日起始权益
- [ ] 如果 `daily_start_date` 不是今天（UTC），更新基准
- [ ] 记录 `daily_start_equity` 和 `daily_start_date`
- [ ] Bot 首次启动时初始化每日基准
- [ ] 添加单元测试

**Technical Notes**:
```python
def update_daily_baseline(state: RiskControlState, current_equity: float) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.daily_start_date != today:
        state.daily_start_date = today
        state.daily_start_equity = current_equity
        state.daily_loss_pct = 0.0
        state.daily_loss_triggered = False
        logging.info("Daily baseline reset: equity=%.2f, date=%s", current_equity, today)
```

---

### Story 7.3.2: 实现每日亏损百分比计算

**As a** system  
**I want** to calculate daily loss percentage in real-time  
**So that** I can trigger limits when threshold is reached

**Acceptance Criteria**:
- [ ] 实现 `calculate_daily_loss_pct(state, current_equity)` 函数
- [ ] 计算公式: `(current_equity - daily_start_equity) / daily_start_equity * 100`
- [ ] 处理 `daily_start_equity` 为 0 或 None 的边界情况
- [ ] 更新 `state.daily_loss_pct` 字段
- [ ] 添加单元测试

**Technical Notes**:
```python
def calculate_daily_loss_pct(state: RiskControlState, current_equity: float) -> float:
    if not state.daily_start_equity or state.daily_start_equity <= 0:
        return 0.0
    loss_pct = ((current_equity - state.daily_start_equity) / state.daily_start_equity) * 100
    state.daily_loss_pct = loss_pct
    return loss_pct
```

---

### Story 7.3.3: 实现每日亏损阈值触发

**As a** system  
**I want** to automatically activate Kill-Switch when daily loss limit is reached  
**So that** further losses are prevented

**Acceptance Criteria**:
- [ ] 在每次迭代时检查每日亏损是否达到阈值
- [ ] 阈值判断: `daily_loss_pct <= -DAILY_LOSS_LIMIT_PCT`
- [ ] 达到阈值时调用 `activate_kill_switch()` 并设置 `daily_loss_triggered=True`
- [ ] 发送详细的 Telegram 通知
- [ ] 添加单元测试

**Technical Notes**:
```python
def check_daily_loss_limit(state: RiskControlState, current_equity: float) -> bool:
    if not DAILY_LOSS_LIMIT_ENABLED:
        return False
    
    loss_pct = calculate_daily_loss_pct(state, current_equity)
    
    if loss_pct <= -DAILY_LOSS_LIMIT_PCT and not state.daily_loss_triggered:
        activate_kill_switch(state, f"Daily loss limit reached: {loss_pct:.2f}%")
        state.daily_loss_triggered = True
        notify_daily_loss_limit_triggered(loss_pct, DAILY_LOSS_LIMIT_PCT)
        return True
    return False
```

---

### Story 7.3.4: 实现每日亏损限制通知

**As a** user  
**I want** detailed notifications when daily loss limit is triggered  
**So that** I understand the situation and can take action

**Acceptance Criteria**:
- [ ] 触发时发送通知，包含：
  - 当前亏损百分比
  - 配置的阈值
  - 当日起始权益
  - 当前权益
  - 恢复选项说明
- [ ] 通知使用醒目的格式（emoji + Markdown）
- [ ] 添加单元测试

**Technical Notes**:
```python
def notify_daily_loss_limit_triggered(loss_pct: float, limit_pct: float) -> None:
    message = f"""🔴 *每日亏损限制已触发*

*当前亏损:* {loss_pct:.2f}%
*限制阈值:* -{limit_pct:.2f}%

*当日起始权益:* ${state.daily_start_equity:.2f}
*当前权益:* ${current_equity:.2f}

⚠️ 所有新开仓已暂停
✅ 现有持仓 SL/TP 继续生效

*选项:*
• 等待次日 UTC 00:00 自动重置
• 发送 `/reset_daily` 手动重置基准
• 发送 `/resume` 强制恢复（谨慎）"""
    send_telegram_message(message)
```

---

## Epic 7.4: Telegram 命令集成

### Epic 概述

**目标**: 实现 Telegram 命令接收和处理，允许用户远程控制风控系统。

**范围**:
- Telegram 命令接收机制
- 命令处理器实现
- 安全校验
- 帮助信息

**验收标准**:
- 用户可以通过 Telegram 命令控制 Kill-Switch
- 命令仅接受来自配置的 Chat ID
- 敏感操作需要二次确认

**依赖**: Epic 7.2, Epic 7.3

---

### Story 7.4.1: 实现 Telegram 命令接收机制

**As a** system  
**I want** to receive and parse Telegram commands  
**So that** users can control the bot remotely

**Acceptance Criteria**:
- [ ] 创建 `notifications/telegram_commands.py` 模块
- [ ] 实现 `TelegramCommandHandler` 类
- [ ] 使用 Telegram Bot API 的 `getUpdates` 方法轮询消息
- [ ] 解析以 `/` 开头的命令消息
- [ ] 在每次迭代开始时检查新命令
- [ ] 添加单元测试

**Technical Notes**:
```python
class TelegramCommandHandler:
    def __init__(self, bot_token: str, allowed_chat_id: str):
        self.bot_token = bot_token
        self.allowed_chat_id = allowed_chat_id
        self.last_update_id = 0
    
    def poll_commands(self) -> List[TelegramCommand]:
        # 调用 getUpdates API
        # 过滤来自 allowed_chat_id 的消息
        # 解析命令
        pass
```

---

### Story 7.4.2: 实现 /kill 和 /resume 命令

**As a** user  
**I want** to control Kill-Switch via Telegram commands  
**So that** I can quickly respond to market events

**Acceptance Criteria**:
- [ ] `/kill` 命令激活 Kill-Switch
- [ ] `/resume` 命令在 Kill-Switch 激活且未被每日亏损限制阻挡时直接解除 Kill-Switch
- [ ] 命令执行后发送确认消息
- [ ] 添加单元测试

**Technical Notes**:
```python
def handle_command(command: str, args: List[str]) -> str:
    if command == "kill":
        activate_kill_switch(risk_control_state, "Manual trigger via Telegram")
        return "✅ Kill-Switch 已激活"
    
    elif command == "resume":
        if args and args[0] == "confirm":
            if deactivate_kill_switch(risk_control_state):
                return "✅ Kill-Switch 已解除，交易恢复"
            else:
                return "⚠️ 无法解除：每日亏损限制仍在生效"
```

---

### Story 7.4.3: 实现 /status 命令

**As a** user  
**I want** to check current risk control status via Telegram  
**So that** I can monitor the bot's risk state

**Acceptance Criteria**:
- [ ] `/status` 命令返回当前风控状态
- [ ] 显示内容包括：
  - Kill-Switch 状态
  - 每日亏损百分比
  - 每日亏损限制阈值
  - 当前持仓数量
  - 当前权益
- [ ] 使用清晰的格式展示
- [ ] 添加单元测试

**Technical Notes**:
```python
def handle_status_command() -> str:
    status = "🟢 正常" if not risk_control_state.kill_switch_active else "🔴 已暂停"
    return f"""📊 *风控状态*

*交易状态:* {status}
*Kill-Switch:* {"激活" if risk_control_state.kill_switch_active else "未激活"}
*触发原因:* {risk_control_state.kill_switch_reason or "N/A"}

*每日亏损:* {risk_control_state.daily_loss_pct:.2f}%
*限制阈值:* -{DAILY_LOSS_LIMIT_PCT:.2f}%

*当前持仓:* {len(positions)} 个
*当前权益:* ${current_equity:.2f}"""
```

---

### Story 7.4.4: 实现 /reset_daily 命令

**As a** user  
**I want** to manually reset daily loss baseline  
**So that** I can continue trading after reviewing the situation

**Acceptance Criteria**:
- [ ] `/reset_daily` 命令重置每日起始权益为当前权益
- [ ] 重置 `daily_loss_pct` 为 0
- [ ] 重置 `daily_loss_triggered` 为 False
- [ ] 如果 Kill-Switch 是由每日亏损触发的，同时解除 Kill-Switch
- [ ] 发送确认消息
- [ ] 添加单元测试

**Technical Notes**:
```python
def handle_reset_daily_command() -> str:
    current_equity = calculate_total_equity()
    risk_control_state.daily_start_equity = current_equity
    risk_control_state.daily_start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    risk_control_state.daily_loss_pct = 0.0
    
    if risk_control_state.daily_loss_triggered:
        risk_control_state.daily_loss_triggered = False
        deactivate_kill_switch(risk_control_state, force=True)
        return f"✅ 每日基准已重置，Kill-Switch 已解除\n新基准: ${current_equity:.2f}"
    
    return f"✅ 每日基准已重置\n新基准: ${current_equity:.2f}"
```

---

### Story 7.4.5: 实现 /help 命令和安全校验

**As a** user  
**I want** help information and secure command handling  
**So that** I know available commands and the bot is protected

**Acceptance Criteria**:
- [ ] `/help` 命令返回所有可用命令列表
- [ ] 仅处理来自 `TELEGRAM_CHAT_ID` 的命令
- [ ] 来自其他 Chat ID 的命令被忽略并记录日志
- [ ] 未知命令返回帮助提示
- [ ] 添加单元测试

**Technical Notes**:
```python
HELP_MESSAGE = """📋 *可用命令*

*/kill* - 激活 Kill-Switch，暂停所有新开仓
*/resume* - 解除 Kill-Switch，恢复交易
*/status* - 查看当前风控状态
*/reset_daily* - 重置每日亏损基准
*/help* - 显示此帮助信息"""

def handle_command(chat_id: str, command: str, args: List[str]) -> Optional[str]:
    if chat_id != TELEGRAM_CHAT_ID:
        logging.warning("Ignoring command from unauthorized chat: %s", chat_id)
        return None
    
    if command == "help":
        return HELP_MESSAGE
    # ... 其他命令处理
```

---

## 实施顺序建议

```
Week 1: Epic 7.1 (基础设施)
├── Story 7.1.1: 数据结构
├── Story 7.1.2: 环境变量
├── Story 7.1.3: 持久化
└── Story 7.1.4: 主循环集成

Week 2: Epic 7.2 (Kill-Switch)
├── Story 7.2.1: 激活逻辑
├── Story 7.2.2: 解除逻辑
├── Story 7.2.3: 信号过滤
├── Story 7.2.4: SL/TP 验证
└── Story 7.2.5: 通知

Week 3: Epic 7.3 (每日亏损限制)
├── Story 7.3.1: 每日基准
├── Story 7.3.2: 亏损计算
├── Story 7.3.3: 阈值触发
└── Story 7.3.4: 通知

Week 4: Epic 7.4 (Telegram 命令)
├── Story 7.4.1: 命令接收
├── Story 7.4.2: /kill /resume
├── Story 7.4.3: /status
├── Story 7.4.4: /reset_daily
└── Story 7.4.5: /help 和安全
```

---

## 测试策略

### 单元测试

每个 Story 都需要对应的单元测试，覆盖：
- 正常路径
- 边界条件
- 错误处理

### 集成测试

- Kill-Switch 激活后的完整迭代流程
- 每日亏损触发后的行为
- Telegram 命令端到端测试

### 手动测试场景

1. 设置 `KILL_SWITCH=true` 启动 Bot，验证无新开仓
2. 模拟亏损达到阈值，验证自动暂停
3. 通过 Telegram 命令控制 Kill-Switch
4. 跨日测试每日重置逻辑

---

## FR 覆盖矩阵

| FR | Story | 状态 |
|----|-------|------|
| FR1-FR4 | 7.1.1, 7.1.3, 7.1.4 | 待实现 |
| FR5-FR6 | 7.2.1, 7.4.2 | 待实现 |
| FR7-FR8 | 7.2.3, 7.2.4 | 待实现 |
| FR9-FR11 | 7.2.2, 7.2.5, 7.4.2 | 待实现 |
| FR12-FR18 | 7.3.1-7.3.4, 7.4.4 | 待实现 |
| FR19-FR21 | 7.2.5, 7.4.3 | 待实现 |
| FR22-FR24 | 7.4.1, 7.4.5 | 待实现 |

---

_本文档将 PRD 中的 24 条功能需求分解为 4 个 Epic、18 个 Story，为实现提供清晰的路线图。_

_Created: 2025-11-30 by Nick with AI facilitator (PM John)_
