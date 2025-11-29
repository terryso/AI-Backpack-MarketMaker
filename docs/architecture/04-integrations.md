## 4. 外部依赖与集成点

### 4.1 市场数据源

| 数据源 | 模块 | 用途 | 配置 |
|--------|------|------|------|
| **Binance** | `exchange/market_data.py` | K 线数据获取（默认） | `BN_API_KEY`, `BN_SECRET` |
| **Backpack** | `exchange/market_data.py` | K 线数据获取（可选） | `MARKET_DATA_BACKEND=backpack` |

### 4.2 交易执行后端

| 后端 | 模块 | 说明 | 配置 |
|------|------|------|------|
| **Paper Trading** | 内存模拟 | 默认模式，无实际下单 | `TRADING_BACKEND=paper` |
| **Hyperliquid** | `exchange/hyperliquid.py` | 永续合约交易 | `TRADING_BACKEND=hyperliquid`, `HYPERLIQUID_LIVE_TRADING=true` |
| **Binance Futures** | `exchange/binance.py` | 合约交易 | `TRADING_BACKEND=binance_futures`, `BINANCE_FUTURES_LIVE=true` |
| **Backpack** | `exchange/backpack.py` | 交易所交易 | `TRADING_BACKEND=backpack`, `BACKPACK_FUTURES_LIVE=true` |

### 4.3 LLM 服务

| 服务 | 模块 | 说明 | 配置 |
|------|------|------|------|
| **OpenRouter** | `llm/client.py` | 默认 LLM 网关 | `OPENROUTER_API_KEY`, `LLM_API_TYPE=openrouter` |
| **OpenAI 兼容接口** | `llm/client.py` | 自定义 LLM 端点 | `LLM_API_TYPE=openai`, `LLM_API_BASE_URL`, `LLM_API_KEY` |

默认模型：`deepseek/deepseek-chat-v3.1`（通过 OpenRouter）

### 4.4 通知服务

| 服务 | 模块 | 用途 | 配置 |
|------|------|------|------|
| **Telegram** | `notifications/telegram.py` | 运维与信号通知 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

### 4.5 交易所接口统一抽象

所有交易所后端实现统一的 `ExchangeClient` Protocol（定义于 `exchange/base.py`）：

```python
@runtime_checkable
class ExchangeClient(Protocol):
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
    ) -> EntryResult: ...

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **kwargs: Any,
    ) -> CloseResult: ...
```

### 4.6 集成配置入口

- **环境变量**：所有敏感信息通过 `.env` 文件或运行环境注入。
- **配置示例**：根目录 `.env.example` 包含所有可配置项的说明。
- **文档入口**：README 中的「Trading Backends & Live Mode Configuration」小节。

### 4.7 新增交易所适配器指南

1. 在 `exchange/` 目录下创建新的适配器文件（如 `exchange/new_exchange.py`）。
2. 实现 `ExchangeClient` Protocol 的 `place_entry()` 和 `close_position()` 方法。
3. 在 `exchange/factory.py` 中注册新的后端类型。
4. 在 `.env.example` 中添加相关配置项说明。
5. 创建 `scripts/manual_<exchange>_smoke.py` 进行连通性测试。
