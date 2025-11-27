## 4. 外部依赖与集成点

- **Binance**：
  - 行情拉取（现货/合约 K 线）。
  - 回测与实时交易均依赖。
- **OpenRouter + DeepSeek**：
  - 中心化的 LLM 决策端点，实现策略逻辑的「大脑」。
- **Hyperliquid**：
  - 可选的实盘执行端，对接钱包与合约帐户。
- **Telegram**：
  - 作为运维与信号通知渠道。

集成方式：均通过环境变量进行配置，避免硬编码密钥与敏感信息；
对于交易 backend 与实盘开关，统一入口为根目录 `.env.example` 与 README 中的「Trading Backends & Live Mode Configuration」小节。
