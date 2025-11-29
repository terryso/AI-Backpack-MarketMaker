# LLM-Trader 代码重构计划

## 1. 重构目标

### 1.1 核心问题
1. **代码重复**：`trading_loop.py` 和 `trade_execution.py` 存在大量重复代码
2. **职责混杂**：`strategy_core.py` 混合了指标计算、Prompt构建、消息格式化、JSON解析等不相关职责
3. **命名混淆**：`exchange_client.py` 和 `exchange_clients.py` 名称过于相似
4. **上帝模块**：`bot.py` 承担过多职责，重新导出大量函数

### 1.2 重构原则
- **单一职责原则**：每个模块只负责一个明确的功能领域
- **最小依赖原则**：减少模块间的循环依赖和不必要的依赖链
- **向后兼容**：保持对外接口稳定，确保测试和 backtest.py 正常工作
- **渐进式重构**：分阶段进行，每阶段可独立验证

---

## 2. 目标架构

### 2.1 模块结构
```
LLM-trader-test/
├── bot.py                      # 主入口，仅协调和启动
├── backtest.py                 # 回测入口（保持不变）
│
├── config/                     # 配置层
│   ├── __init__.py
│   ├── settings.py             # 配置加载（原 trading_config.py）
│   └── constants.py            # 常量定义
│
├── core/                       # 核心业务层
│   ├── __init__.py
│   ├── state.py                # 状态管理（原 trading_state.py）
│   ├── persistence.py          # 状态持久化（原 state_io.py）
│   └── metrics.py              # 指标计算（原 metrics.py）
│
├── exchange/                   # 交易所层
│   ├── __init__.py
│   ├── base.py                 # 抽象接口 ExchangeClient
│   ├── factory.py              # 客户端工厂（原 exchange_clients.py）
│   ├── hyperliquid.py          # Hyperliquid 实现
│   ├── binance.py              # Binance 实现
│   ├── backpack.py             # Backpack 实现
│   └── market_data.py          # 市场数据（原 market_data.py）
│
├── execution/                  # 执行层
│   ├── __init__.py
│   ├── executor.py             # 交易执行器（合并 trade_execution.py）
│   ├── routing.py              # 路由逻辑（原 execution_routing.py）
│   └── sltp.py                 # 止损止盈逻辑
│
├── strategy/                   # 策略层
│   ├── __init__.py
│   ├── indicators.py           # 技术指标计算
│   ├── snapshot.py             # 市场快照构建
│   └── signals.py              # 信号生成逻辑
│
├── llm/                        # LLM 层
│   ├── __init__.py
│   ├── client.py               # LLM API 调用
│   ├── prompt.py               # Prompt 构建
│   └── parser.py               # 响应解析
│
├── display/                    # 显示层
│   ├── __init__.py
│   ├── portfolio.py            # 投资组合显示
│   ├── console.py              # 控制台输出
│   └── formatters.py           # 消息格式化
│
├── notifications/              # 通知层
│   ├── __init__.py
│   ├── telegram.py             # Telegram 通知
│   └── logging.py              # 日志记录
│
└── utils/                      # 工具层
    ├── __init__.py
    └── text.py                 # 文本处理工具
```

### 2.2 依赖关系图
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

---

## 3. 重构阶段

### 阶段 1：创建 utils 模块（低风险）✅ 已完成
**目标**：提取重复的工具函数

**任务**：
- [x] 创建 `utils/__init__.py`
- [x] 创建 `utils/text.py`，包含：
  - `strip_ansi_codes()` - 从 `trading_state.py` 和 `notifications.py` 合并
  - `escape_markdown()` - 从 `trading_state.py` 和 `notifications.py` 合并
- [ ] 更新 `trading_state.py` 和 `notifications.py` 导入（保留原实现以保持兼容性）

### 阶段 2：拆分 strategy_core.py（中风险）✅ 已完成
**目标**：将混杂的职责分离到独立模块

**任务**：
- [x] 创建 `strategy/__init__.py`
- [x] 创建 `strategy/indicators.py`，包含：
  - `calculate_rsi_series()`
  - `add_indicator_columns()`
  - `calculate_atr_series()`
  - `calculate_indicators()`
  - `round_series()`
- [x] 创建 `strategy/snapshot.py`，包含：
  - `build_market_snapshot()`
- [x] 创建 `llm/__init__.py`
- [x] 创建 `llm/prompt.py`，包含：
  - `build_trading_prompt()`
- [x] 创建 `llm/parser.py`，包含：
  - `recover_partial_decisions()`
  - `parse_llm_json_decisions()`
- [x] 创建 `display/__init__.py`
- [x] 创建 `display/formatters.py`，包含：
  - `build_entry_signal_message()`
  - `build_close_signal_message()`
- [x] 保留 `strategy_core.py` 作为兼容层，重新导出所有函数

### 阶段 3：合并执行逻辑（高风险）✅ 已完成
**目标**：消除 `trading_loop.py` 和 `trade_execution.py` 的重复

**任务**：
- [x] 创建 `execution/__init__.py`
- [x] 创建 `execution/executor.py`，包含统一的 `TradeExecutor` 类
- [x] 创建 `execution/routing.py`（从 `execution_routing.py` 提取）
- [x] 保留 `trade_execution.py` 作为兼容层
- [x] 保留 `execution_routing.py` 作为兼容层

### 阶段 4：重组交易所模块（中风险）✅ 已完成
**目标**：清晰区分接口定义和客户端管理

**任务**：
- [x] 创建 `exchange/__init__.py`
- [x] 创建 `exchange/base.py`，包含：
  - `EntryResult` dataclass
  - `CloseResult` dataclass
  - `ExchangeClient` Protocol
- [x] 创建 `exchange/hyperliquid.py`，包含 `HyperliquidExchangeClient`
- [x] 创建 `exchange/binance.py`，包含 `BinanceFuturesExchangeClient`
- [x] 创建 `exchange/backpack.py`，包含 `BackpackFuturesExchangeClient`
- [x] 创建 `exchange/factory.py`（包含客户端工厂函数）
- [x] 保留 `exchange_client.py` 作为兼容层

### 阶段 5：简化 bot.py（低风险）✅ 已完成
**目标**：将 bot.py 简化为纯协调层

**任务**：
- [x] 通过前面阶段的重构，bot.py 的职责已经大幅简化
- [x] 核心逻辑已移至独立模块（strategy/, llm/, display/, exchange/, execution/）
- [x] bot.py 现在主要作为协调层，导入和组合各模块功能
- [x] 保留主循环和启动逻辑
- [x] 保留向后兼容的函数包装（供测试使用）

---

## 4. 详细设计

### 4.1 utils/text.py
```python
"""Text processing utilities."""
import re

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes from text."""
    return ANSI_ESCAPE_RE.sub("", text)

def escape_markdown(text: str) -> str:
    """Escape Telegram Markdown special characters."""
    if not text:
        return text
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join(f"\\{char}" if char in specials else char for char in text)
```

### 4.2 strategy/indicators.py
```python
"""Technical indicator calculations."""
from typing import Any, Iterable, List
import numpy as np
import pandas as pd

def calculate_rsi_series(close: pd.Series, period: int) -> pd.Series:
    """Return RSI series using Wilder's smoothing."""
    ...

def add_indicator_columns(
    df: pd.DataFrame,
    ema_lengths: Iterable[int],
    rsi_periods: Iterable[int],
    macd_params: Iterable[int],
) -> pd.DataFrame:
    """Add EMA, RSI, and MACD columns to dataframe."""
    ...

def calculate_atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate Average True Range series."""
    ...

def calculate_indicators(
    df: pd.DataFrame,
    ema_len: int,
    rsi_len: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
) -> pd.Series:
    """Calculate indicators and return latest row."""
    ...

def round_series(values: Iterable[Any], precision: int) -> List[float]:
    """Round numeric values to given precision."""
    ...
```

### 4.3 exchange/base.py
```python
"""Exchange client base definitions."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

@dataclass(slots=True)
class EntryResult:
    """Unified entry result structure."""
    success: bool
    backend: str
    errors: List[str]
    entry_oid: Optional[Any] = None
    tp_oid: Optional[Any] = None
    sl_oid: Optional[Any] = None
    raw: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class CloseResult:
    """Unified close result structure."""
    success: bool
    backend: str
    errors: List[str]
    close_oid: Optional[Any] = None
    raw: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class ExchangeClient(Protocol):
    """Unified exchange execution interface."""
    
    def place_entry(
        self,
        coin: str,
        side: str,
        size: float,
        entry_price: Optional[float],
        stop_loss_price: Optional[float],
        take_profit_price: Optional[float],
        leverage: float,
        liquidity: str,
        **kwargs: Any,
    ) -> EntryResult:
        ...

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **kwargs: Any,
    ) -> CloseResult:
        ...
```

### 4.4 execution/executor.py
```python
"""Unified trade execution."""
from typing import Any, Callable, Dict, Optional

class TradeExecutor:
    """Handles all trade execution with dependency injection."""
    
    def __init__(self, dependencies: Dict[str, Any]):
        self._deps = dependencies
    
    def execute_entry(self, coin: str, decision: Dict, price: float) -> None:
        """Execute entry trade."""
        ...
    
    def execute_close(self, coin: str, decision: Dict, price: float) -> None:
        """Execute close trade."""
        ...
    
    def process_hold(self, coin: str, decision: Dict, price: float) -> None:
        """Process hold signal."""
        ...
    
    def process_decisions(self, decisions: Dict[str, Any]) -> None:
        """Process all AI decisions."""
        ...
    
    def check_stop_loss_take_profit(self) -> None:
        """Check and execute SL/TP for all positions."""
        ...
```

---

## 5. 兼容性策略

### 5.1 保留兼容层
为确保现有代码（测试、backtest.py）继续工作，保留以下兼容层：

```python
# strategy_core.py - 兼容层
from strategy.indicators import (
    calculate_rsi_series,
    add_indicator_columns,
    calculate_atr_series,
    calculate_indicators,
    round_series,
)
from strategy.snapshot import build_market_snapshot
from llm.prompt import build_trading_prompt
from llm.parser import recover_partial_decisions, parse_llm_json_decisions
from display.formatters import build_entry_signal_message, build_close_signal_message

__all__ = [
    "calculate_rsi_series",
    "add_indicator_columns",
    # ... 所有原有导出
]
```

### 5.2 废弃警告
在兼容层添加废弃警告，引导用户迁移：

```python
import warnings

def _deprecated_import_warning(old_module: str, new_module: str):
    warnings.warn(
        f"Importing from '{old_module}' is deprecated. "
        f"Please import from '{new_module}' instead.",
        DeprecationWarning,
        stacklevel=3,
    )
```

---

## 6. 测试策略

### 6.1 每阶段验证
每个阶段完成后执行：
```bash
# 运行所有测试
pytest tests/ -v

# 检查导入是否正常
python -c "import bot; import backtest; print('OK')"

# 运行类型检查（如果配置了）
mypy bot.py backtest.py
```

### 6.2 回归测试
确保以下功能正常：
- [ ] `bot.py` 主循环启动
- [ ] `backtest.py` 回测运行
- [ ] 所有现有测试通过
- [ ] Telegram 通知发送
- [ ] 交易执行（paper 模式）

---

## 7. 实施时间表

| 阶段 | 预计时间 | 风险等级 |
|------|----------|----------|
| 阶段 1：utils 模块 | 15 分钟 | 低 |
| 阶段 2：拆分 strategy_core | 45 分钟 | 中 |
| 阶段 3：合并执行逻辑 | 60 分钟 | 高 |
| 阶段 4：重组交易所模块 | 45 分钟 | 中 |
| 阶段 5：简化 bot.py | 30 分钟 | 低 |
| **总计** | **约 3.5 小时** | - |

---

## 8. 回滚计划

如果重构导致问题：
1. 每个阶段完成后创建 Git commit
2. 保留所有原始文件的兼容层
3. 如需回滚，可以 `git revert` 到任意阶段

---

## 9. 成功标准

- [ ] 所有测试通过
- [ ] `bot.py` 行数减少 50%+
- [ ] 无循环依赖
- [ ] 每个模块职责单一明确
- [ ] 代码重复率降低 80%+
