# Epic 技术规格: 风控状态管理基础设施

Date: 2025-11-30
Author: Nick
Epic ID: 7-1
Status: Draft

---

## Overview

本技术规格定义 Epic 7.1「风控状态管理基础设施」的详细设计，为 DeepSeek Paper Trading Bot 建立风控系统的数据结构、状态管理和持久化基础设施。

Epic 7.1 是整个风控系统增强（Epic 7.x 系列）的基础，后续的 Kill-Switch（Epic 7.2）、每日亏损限制（Epic 7.3）和 Telegram 命令集成（Epic 7.4）都依赖于本 Epic 提供的基础设施。

**核心目标**：
- 定义 `RiskControlState` 数据结构，统一管理所有风控状态
- 实现风控状态的持久化，确保 Bot 重启后状态不丢失
- 将风控检查集成到主循环，实现实时风控

## Objectives and Scope

### In Scope

1. **数据结构定义**
   - 创建 `core/risk_control.py` 模块
   - 定义 `RiskControlState` dataclass
   - 实现序列化/反序列化方法

2. **环境变量配置**
   - `RISK_CONTROL_ENABLED`：风控系统总开关
   - `KILL_SWITCH`：启动时 Kill-Switch 状态
   - `DAILY_LOSS_LIMIT_ENABLED`：每日亏损限制开关
   - `DAILY_LOSS_LIMIT_PCT`：每日亏损阈值百分比

3. **状态持久化**
   - 扩展 `portfolio_state.json` 添加 `risk_control` 字段
   - 实现原子写入防止数据损坏
   - 处理旧版本 JSON 文件的向后兼容

4. **主循环集成**
   - 在 `bot.py` 中添加风控状态管理
   - 在每次迭代开始时加载和检查风控状态
   - 在迭代结束时保存风控状态

### Out of Scope

- Kill-Switch 的激活/解除逻辑（Epic 7.2）
- 每日亏损计算和触发逻辑（Epic 7.3）
- Telegram 命令处理（Epic 7.4）
- Web 控制面板
- 多账户风控

## System Architecture Alignment

### 组件定位

根据现有架构（`docs/architecture/02-components.md`），风控模块将作为 `core/` 层的新增组件：

```
core/
├── __init__.py
├── metrics.py
├── persistence.py
├── state.py
├── trading_loop.py
└── risk_control.py  # 新增
```

### 依赖关系

```
bot.py
   │
   ▼
core/risk_control.py ──► core/state.py
   │                         │
   ▼                         ▼
config/settings.py      core/persistence.py
```

### 数据流集成点

根据 `docs/architecture/03-data-flow.md`，风控检查将插入到「数据输入阶段」之后、「策略分析阶段」之前：

```
数据输入阶段
     ↓
┌─────────────────────────────────────────┐
│  风控检查阶段 (新增)                      │
│  core/risk_control.py                   │
│  └── check_risk_limits()                │
│      ├── 检查 Kill-Switch 状态           │
│      └── 更新每日亏损基准（如需）          │
└─────────────────────────────────────────┘
     ↓
策略分析阶段
```

## Detailed Design

### Services and Modules

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `core/risk_control.py` | 风控状态管理 | 配置、当前权益 | `RiskControlState` |
| `config/settings.py` | 风控配置加载 | 环境变量 | 配置常量 |
| `core/persistence.py` | 状态持久化 | `RiskControlState` | JSON 文件 |
| `core/state.py` | 状态协调 | - | 全局状态访问 |

### Data Models and Contracts

#### RiskControlState Dataclass

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class RiskControlState:
    """风控系统状态数据结构。
    
    Attributes:
        kill_switch_active: Kill-Switch 是否激活
        kill_switch_reason: Kill-Switch 触发原因
        kill_switch_triggered_at: Kill-Switch 触发时间 (ISO 8601 字符串)
        daily_start_equity: 当日起始权益
        daily_start_date: 当日起始日期 (YYYY-MM-DD)
        daily_loss_pct: 当日亏损百分比 (负数表示亏损)
        daily_loss_triggered: 是否由每日亏损触发了 Kill-Switch
    """
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_triggered_at: Optional[str] = None
    daily_start_equity: Optional[float] = None
    daily_start_date: Optional[str] = None
    daily_loss_pct: float = 0.0
    daily_loss_triggered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，用于 JSON 持久化。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskControlState":
        """从字典反序列化，处理缺失字段。"""
        return cls(
            kill_switch_active=data.get("kill_switch_active", False),
            kill_switch_reason=data.get("kill_switch_reason"),
            kill_switch_triggered_at=data.get("kill_switch_triggered_at"),
            daily_start_equity=data.get("daily_start_equity"),
            daily_start_date=data.get("daily_start_date"),
            daily_loss_pct=data.get("daily_loss_pct", 0.0),
            daily_loss_triggered=data.get("daily_loss_triggered", False),
        )
```

#### portfolio_state.json 扩展结构

```json
{
  "balance": 10000.0,
  "positions": {},
  "iteration": 42,
  "updated_at": "2025-11-30T12:00:00+00:00",
  "risk_control": {
    "kill_switch_active": false,
    "kill_switch_reason": null,
    "kill_switch_triggered_at": null,
    "daily_start_equity": 10000.0,
    "daily_start_date": "2025-11-30",
    "daily_loss_pct": 0.0,
    "daily_loss_triggered": false
  }
}
```

### APIs and Interfaces

#### core/risk_control.py 公共接口

```python
# 状态管理
def get_risk_control_state() -> RiskControlState:
    """获取当前风控状态（全局单例）。"""

def set_risk_control_state(state: RiskControlState) -> None:
    """设置风控状态（用于测试或重置）。"""

def reset_risk_control_state() -> None:
    """重置风控状态为默认值。"""

# 持久化
def load_risk_control_state(data: Dict[str, Any]) -> None:
    """从 JSON 数据加载风控状态。"""

def save_risk_control_state() -> Dict[str, Any]:
    """导出风控状态为字典，用于 JSON 持久化。"""

# 配置检查
def is_risk_control_enabled() -> bool:
    """检查风控系统是否启用。"""

def should_block_entry() -> bool:
    """检查是否应阻止新开仓（Kill-Switch 激活时返回 True）。"""
```

#### config/settings.py 新增配置

```python
# 风控配置
RISK_CONTROL_ENABLED: bool  # 默认 True
KILL_SWITCH: bool           # 默认 False
DAILY_LOSS_LIMIT_ENABLED: bool  # 默认 True
DAILY_LOSS_LIMIT_PCT: float     # 默认 5.0
```

### Workflows and Sequencing

#### 启动时序

```
1. bot.py 启动
   │
   ▼
2. config/settings.py 加载环境变量
   ├── RISK_CONTROL_ENABLED
   ├── KILL_SWITCH
   ├── DAILY_LOSS_LIMIT_ENABLED
   └── DAILY_LOSS_LIMIT_PCT
   │
   ▼
3. core/state.py load_state()
   │
   ▼
4. core/persistence.py load_state_from_json()
   ├── 加载 balance, positions, iteration
   └── 加载 risk_control (如存在)
   │
   ▼
5. core/risk_control.py load_risk_control_state()
   ├── 如果 JSON 中有 risk_control → 恢复状态
   ├── 如果 JSON 中无 risk_control → 使用默认值
   └── 如果 KILL_SWITCH=true → 激活 Kill-Switch
   │
   ▼
6. 进入主循环
```

#### 迭代时序

```
_run_iteration() 开始
   │
   ▼
1. 风控检查 (新增)
   ├── is_risk_control_enabled() → 如果 False，跳过风控
   ├── should_block_entry() → 返回 Kill-Switch 状态
   └── (后续 Epic 添加更多检查)
   │
   ▼
2. 拉取行情数据
   │
   ▼
3. 计算技术指标
   │
   ▼
4. 调用 LLM 获取决策
   │
   ▼
5. 处理决策 (如果 should_block_entry() 为 True，跳过 entry)
   │
   ▼
6. 更新状态
   │
   ▼
7. 保存状态 (包含 risk_control)
   │
   ▼
_run_iteration() 结束
```

## Non-Functional Requirements

### Performance

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| 风控状态检查延迟 | < 1ms | 内存操作，无 I/O |
| 状态持久化延迟 | < 50ms | 与现有 save_state 合并 |
| 内存占用增量 | < 1KB | RiskControlState 实例大小 |

**依据**：PRD NFR1 要求风控检查增加的延迟 < 100ms，本设计通过内存操作实现，远低于要求。

### Security

- **配置安全**：风控配置通过环境变量注入，不硬编码
- **状态完整性**：使用原子写入防止状态文件损坏
- **默认安全**：`RISK_CONTROL_ENABLED` 默认为 `true`，`KILL_SWITCH` 默认为 `false`

### Reliability/Availability

- **状态恢复**：Bot 重启后自动恢复风控状态
- **向后兼容**：旧版本 JSON 文件（无 `risk_control` 字段）可正常加载
- **降级策略**：如果风控模块加载失败，记录错误但不阻止 Bot 启动

### Observability

| 日志事件 | 级别 | 格式 |
|----------|------|------|
| 风控状态加载 | INFO | `Risk control state loaded: kill_switch={}, daily_loss_pct={:.2f}%` |
| 风控状态保存 | DEBUG | `Risk control state saved` |
| Kill-Switch 状态变更 | WARNING | `Kill-Switch {activated|deactivated}: {reason}` |
| 配置加载 | INFO | `Risk control config: enabled={}, kill_switch={}, daily_limit={}%` |

## Dependencies and Integrations

### 内部依赖

| 模块 | 依赖类型 | 说明 |
|------|----------|------|
| `config/settings.py` | 导入 | 读取风控配置常量 |
| `core/persistence.py` | 扩展 | 扩展 JSON 读写函数 |
| `core/state.py` | 扩展 | 扩展 load_state/save_state |
| `bot.py` | 集成 | 在主循环中调用风控检查 |

### 外部依赖

无新增外部依赖。使用现有的：
- `dataclasses`（Python 标准库）
- `json`（Python 标准库）
- `logging`（Python 标准库）

### 版本约束

- Python >= 3.10（dataclass 特性）
- 与现有 `requirements.txt` 完全兼容

## Acceptance Criteria (Authoritative)

### AC-7.1.1: RiskControlState 数据结构

1. `core/risk_control.py` 模块存在且可导入
2. `RiskControlState` dataclass 包含所有必需字段
3. `to_dict()` 方法返回可 JSON 序列化的字典
4. `from_dict()` 方法可从字典正确恢复状态
5. 缺失字段时使用合理默认值

### AC-7.1.2: 环境变量配置

1. `RISK_CONTROL_ENABLED` 可通过环境变量配置，默认 `true`
2. `KILL_SWITCH` 可通过环境变量配置，默认 `false`
3. `DAILY_LOSS_LIMIT_ENABLED` 可通过环境变量配置，默认 `true`
4. `DAILY_LOSS_LIMIT_PCT` 可通过环境变量配置，默认 `5.0`
5. `.env.example` 包含新变量说明
6. 无效配置值有警告日志并使用默认值

### AC-7.1.3: 状态持久化

1. `save_state()` 将 `risk_control` 字段写入 `portfolio_state.json`
2. `load_state()` 从 `portfolio_state.json` 恢复 `risk_control` 字段
3. 旧版本 JSON 文件（无 `risk_control`）可正常加载
4. 状态文件使用原子写入（先写临时文件再重命名）
5. Bot 重启后风控状态保持不变

### AC-7.1.4: 主循环集成

1. `bot.py` 中存在全局 `risk_control_state` 变量
2. `load_state()` 调用后风控状态已加载
3. `save_state()` 调用时风控状态被保存
4. `_run_iteration()` 开始时调用风控检查函数
5. `is_risk_control_enabled()` 返回配置值
6. `should_block_entry()` 返回 Kill-Switch 状态

## Traceability Mapping

| AC | 规格章节 | 组件/API | 测试思路 |
|----|----------|----------|----------|
| AC-7.1.1 | Data Models | `RiskControlState` | 单元测试：序列化/反序列化 |
| AC-7.1.2 | APIs - config | `config/settings.py` | 单元测试：环境变量解析 |
| AC-7.1.3 | Workflows - 启动 | `core/persistence.py` | 集成测试：状态恢复 |
| AC-7.1.4 | Workflows - 迭代 | `bot.py` | 集成测试：主循环风控检查 |

## Risks, Assumptions, Open Questions

### Risks

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 状态文件损坏 | 风控状态丢失 | 原子写入 + 启动时校验 |
| 配置冲突 | 行为不一致 | 明确优先级：环境变量 > 持久化状态 |
| 向后兼容问题 | 旧版本 Bot 无法读取新格式 | 仅添加字段，不修改现有结构 |

### Assumptions

1. `portfolio_state.json` 是唯一的状态持久化文件
2. Bot 以单实例运行，无并发写入问题
3. 环境变量在 Bot 运行期间不会动态变化

### Open Questions

1. **Q**: 是否需要支持风控状态的版本迁移？
   **A**: 暂不需要，通过 `from_dict()` 的默认值处理即可

2. **Q**: `KILL_SWITCH` 环境变量与持久化状态冲突时如何处理？
   **A**: 环境变量优先，`KILL_SWITCH=true` 总是激活 Kill-Switch

## Test Strategy Summary

### 单元测试

**文件**: `tests/test_risk_control.py`

```python
# RiskControlState 测试
def test_risk_control_state_default_values():
    """测试默认值初始化。"""

def test_risk_control_state_to_dict():
    """测试序列化。"""

def test_risk_control_state_from_dict():
    """测试反序列化。"""

def test_risk_control_state_from_dict_missing_fields():
    """测试缺失字段处理。"""

# 配置测试
def test_risk_control_config_defaults():
    """测试配置默认值。"""

def test_risk_control_config_from_env():
    """测试从环境变量加载配置。"""

# 状态管理测试
def test_get_set_risk_control_state():
    """测试状态获取和设置。"""

def test_should_block_entry_when_kill_switch_active():
    """测试 Kill-Switch 激活时阻止开仓。"""
```

### 集成测试

**文件**: `tests/test_risk_control_integration.py`

```python
def test_risk_control_state_persistence():
    """测试风控状态持久化和恢复。"""

def test_risk_control_backward_compatibility():
    """测试旧版本 JSON 文件兼容性。"""

def test_risk_control_env_override():
    """测试环境变量覆盖持久化状态。"""
```

### 测试覆盖目标

- 行覆盖率 > 90%
- 分支覆盖率 > 85%
- 所有公共 API 有对应测试

## Post-Review Follow-ups (AI)

- **[Medium] 明确环境变量与持久化状态的优先级策略**  
  - 在后续 Epic（优先建议 Epic 7.2）中补齐 `KILL_SWITCH` 等环境变量与持久化 `RiskControlState` 之间的冲突解决规则，例如：当环境变量显式开启 Kill-Switch 时，应优先于状态文件中的关闭标记。  
  - 相关实现点：`config/settings.py`（配置层）、`core/state.py`（状态加载层）、`core/risk_control.py` / 后续 Kill-Switch 逻辑（行为层）。
- **[Low] 清理风控模块中不必要的 TYPE_CHECKING 引用**  
  - 在合适的后续 Story 中移除 `core/risk_control.py` 中对自身模块的 `TYPE_CHECKING` 引用，以减少类型声明噪音。  
  - 不影响现有行为，属于代码洁净度改进。
- **[Low] 统一风控相关日志格式与位置**  
  - 在后续 Epic 7.2/7.3 实现具体风控逻辑时，一并梳理启动、迭代与异常路径上的风控相关日志（字段顺序、日志级别、消息前缀），提高可观测性一致性。  
  - 相关实现点：`core/state.py`、`bot.py` 以及未来的 Kill-Switch / 每日亏损逻辑。

---

_本技术规格为 Epic 7.1 的实现提供详细设计指导，后续 Story 实现应严格遵循本规格。_
