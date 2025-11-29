## 5. 可扩展性与演进建议

### 5.1 已完成的架构改进

- ✅ **分层模块化重构**：将单体 `bot.py` 拆分为 config、core、strategy、llm、execution、exchange、display、notifications、utils 等独立模块。
- ✅ **统一交易所接口**：通过 `ExchangeClient` Protocol 实现多交易所支持（Hyperliquid、Binance Futures、Backpack）。
- ✅ **配置集中管理**：所有配置统一在 `config/settings.py` 中加载和管理。
- ✅ **LLM 层抽象**：支持 OpenRouter 和 OpenAI 兼容接口，便于切换模型。

### 5.2 未来演进方向

1. **策略与 Prompt 演进**：
   - 将现有 Prompt 抽象为「策略插件」，为不同市场环境或风格提供多版本 Prompt。
   - 在 `strategy/` 模块中增加信号生成逻辑（`signals.py`）。

2. **多 LLM 与投票架构**：
   - 在 `llm/` 层增加「模型路由器」，支持多 LLM 决策与投票制执行。

3. **更强的风控层**：
   - 在 `execution/` 中抽象独立的 Risk Engine，对 LLM 决策做更丰富的事前/事后约束。
   - 可考虑增加 `execution/sltp.py` 专门处理止损止盈逻辑。

4. **消息总线与事件驱动**：
   - 将当前基于循环的架构升级为事件驱动，以便支持多策略并行与更高频率场景。

5. **配置中心**：
   - 将当前 `.env` 配置迁移到结构化配置（例如 YAML），支持配置热更新。

6. **更多交易所支持**：
   - 按照 `exchange/base.py` 中的 `ExchangeClient` Protocol 添加新的交易所适配器。

---

本架构文档描述的是当前仓库体现出的「事实架构」。后续可以通过新增架构视图（例如部署图、时序图、错误处理流程图等）进一步丰富。
