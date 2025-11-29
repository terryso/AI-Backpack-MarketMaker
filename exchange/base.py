"""Exchange client base definitions and abstract interface.

This module defines the unified data structures and protocol for
exchange client implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
