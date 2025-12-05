"""Exchange client base definitions and abstract interface.

This module defines the unified data structures and protocol for
exchange client implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass(slots=True)
class EntryResult:
    """统一的开仓结果结构，用于抽象不同交易所返回的数据。

    Attributes:
        success: 本次请求在交易所侧是否被接受并处于有效/已成交状态。
        backend: 后端标识，例如 "hyperliquid"、"binance_futures" 等。
        errors: 面向用户/开发者的高层错误摘要列表；成功时应为空。
        entry_oid: 主要开仓订单 ID（如有）。
        tp_oid: 关联的止盈订单 ID（如有）。
        sl_oid: 关联的止损订单 ID（如有）。
        raw: 交易所 SDK / REST 客户端返回的原始数据，用于 debug 与扩展。
        extra: 预留的扩展字段字典，用于承载 backend 特有但对上层仍有价值的信息
               （如状态码、撮合细节等），不在统一 schema 中强制规范。
    """

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
    """统一的平仓结果结构，与 EntryResult 保持语义一致。"""

    success: bool
    backend: str
    errors: List[str]
    close_oid: Optional[Any] = None
    raw: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TPSLResult:
    """统一的 TP/SL 更新结果结构。
    
    Attributes:
        success: 是否成功设置 TP/SL。
        backend: 后端标识。
        errors: 错误信息列表。
        sl_order_id: 止损订单 ID（如有）。
        tp_order_id: 止盈订单 ID（如有）。
        raw: 原始响应数据。
    """
    success: bool
    backend: str
    errors: List[str] = field(default_factory=list)
    sl_order_id: Optional[Any] = None
    tp_order_id: Optional[Any] = None
    raw: Optional[Any] = None


@dataclass(slots=True)
class Position:
    """标准化的持仓数据结构。
    
    各交易所客户端应将原始持仓数据转换为此格式，
    使上层命令处理逻辑无需关心交易所差异。
    """
    coin: str                           # 币种名称 (如 "BTC", "ETH")
    side: str                           # "long" 或 "short"
    quantity: float                     # 持仓数量 (绝对值)
    entry_price: float                  # 入场价格
    mark_price: Optional[float] = None  # 标记价格
    leverage: float = 1.0               # 杠杆倍数
    margin: float = 0.0                 # 已用保证金
    notional: float = 0.0               # 名义价值
    unrealized_pnl: float = 0.0         # 未实现盈亏
    realized_pnl: float = 0.0           # 已实现盈亏
    liquidation_price: Optional[float] = None  # 强平价格
    take_profit: Optional[float] = None # 止盈价格
    stop_loss: Optional[float] = None   # 止损价格
    raw: Optional[Dict[str, Any]] = None  # 原始数据 (调试用)


@dataclass(slots=True)
class AccountSnapshot:
    """标准化的账户快照数据结构。
    
    各交易所客户端应将原始账户数据转换为此格式。
    """
    balance: float                      # 可用余额
    total_equity: float                 # 总权益
    total_margin: float                 # 已用保证金
    positions: List[Position]           # 持仓列表
    raw: Optional[Dict[str, Any]] = None  # 原始数据 (调试用)
    
    @property
    def positions_count(self) -> int:
        """持仓数量。"""
        return len(self.positions)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式 (兼容旧接口)。"""
        return {
            "balance": self.balance,
            "total_equity": self.total_equity,
            "total_margin": self.total_margin,
            "positions_count": self.positions_count,
            "positions": self.positions,
        }


@runtime_checkable
class ExchangeClient(Protocol):
    """统一的交易执行抽象接口（Exchange Execution Layer）。

    本接口对应 `docs/epics.md` 中 Epic 6 / Story 6.1 所要求的 ExchangeClient 抽象：
    为 Bot 主循环和策略层提供与具体交易所无关的开仓 / 平仓调用方式。
    """

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
        """提交开仓请求，并在可能的情况下附带止损 / 止盈。

        参数语义需与 Story 6.1 / PRD 4.1/4.2 中对风控与执行行为的约束保持一致，
        但具体撮合细节与特殊参数由各 backend 在 **kwargs 中自行扩展实现。
        """
        ...

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **kwargs: Any,
    ) -> CloseResult:
        """提交平仓请求。

        size 省略时表示「全仓平掉当前在该 backend 上的持仓」；
        fallback_price 仅作为在无法从订单簿获取合理价格时的兜底输入，
        是否以及如何使用由具体 backend 决定。
        """
        ...


@dataclass
class AuditData:
    """统一的账户资金变动审计数据结构。
    
    各交易所客户端应将原始审计数据转换为此格式，
    使上层命令处理逻辑无需关心交易所差异。
    
    Attributes:
        backend: 后端标识 (如 "backpack_futures", "binance_futures")。
        funding_total: 资金费合计。
        funding_by_symbol: 按交易对分组的资金费。
        settlement_total: 结算合计 (含手续费、已实现盈亏)。
        settlement_by_source: 按来源分组的结算 (如 TradingFees, RealizePnl)。
        deposit_total: 充值合计。
        withdrawal_total: 提现合计 (负值)。
        raw: 原始数据 (调试用)。
    """
    backend: str
    funding_total: Decimal = field(default_factory=lambda: Decimal("0"))
    funding_by_symbol: Dict[str, Decimal] = field(default_factory=dict)
    settlement_total: Decimal = field(default_factory=lambda: Decimal("0"))
    settlement_by_source: Dict[str, Decimal] = field(default_factory=dict)
    deposit_total: Decimal = field(default_factory=lambda: Decimal("0"))
    withdrawal_total: Decimal = field(default_factory=lambda: Decimal("0"))
    raw: Optional[Dict[str, Any]] = None
    
    @property
    def net_change(self) -> Decimal:
        """计算净变动。"""
        return (
            self.funding_total
            + self.settlement_total
            + self.deposit_total
            + self.withdrawal_total
        )


@runtime_checkable
class AuditProvider(Protocol):
    """账户资金变动审计数据提供者接口。
    
    实现此接口的交易所客户端可以提供资金变动审计功能。
    """
    
    def fetch_audit_data(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> AuditData:
        """获取指定时间范围内的资金变动审计数据。
        
        Args:
            start_utc: 开始时间 (UTC)。
            end_utc: 结束时间 (UTC)。
            
        Returns:
            AuditData 包含资金费、结算、充值、提现等汇总数据。
        """
        ...
