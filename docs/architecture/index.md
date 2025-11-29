# DeepSeek Paper Trading Bot 系统架构说明

## Executive Summary

本文档描述当前系统的组件划分、数据流与外部依赖。

系统采用**分层模块化架构**，实现了一个基于 LLM 的加密货币交易机器人，围绕配置、核心业务、策略、LLM、执行、交易所、显示、通知等层次构建，通过统一的数据目录解耦，使实时交易、历史回测与数据分析共享同一套逻辑与数据结构。

## 架构特点

- **分层模块化**：按职责划分为 config、core、strategy、llm、execution、exchange、display、notifications、utils 等模块。
- **多交易所支持**：通过统一的 `ExchangeClient` Protocol 支持 Hyperliquid、Binance Futures、Backpack 等交易所。
- **依赖注入**：支持回测时注入历史数据客户端，复用核心交易逻辑。
- **可扩展性**：新增交易所只需实现 `ExchangeClient` 接口并注册到工厂。

## 决策总览（Decision Summary）

| Category | Decision | Version | Rationale |
| -------- | -------- | ------- | --------- |
| Architecture | 分层模块化架构 | - | 单一职责原则，降低模块间耦合，便于测试与维护。 |
| Runtime | 使用 Python 3.13.3 作为统一运行时 | 3.13.3 | 与 Docker 基础镜像一致（`python:3.13.3-slim`）。 |
| Data Persistence | 以 `data/` / `data-backtest/` 下的 CSV/JSON 作为主持久化层 | - | 文件存储简单透明，利于回溯与调试。 |
| Trading Architecture | 单进程循环 + 依赖注入式回测 | - | 复用一套指标/决策/执行逻辑于 live 与 backtest。 |
| Exchange Integration | 统一 `ExchangeClient` Protocol | - | 支持多交易所后端，便于扩展。 |
| Live Execution | 默认纸上交易，可选多种实盘后端 | - | Hyperliquid、Binance Futures、Backpack 均已支持。 |
| Visualization | 使用 Streamlit 仪表盘展示组合表现 | streamlit==1.38.0 | 成熟的可视化框架，快速搭建监控界面。 |
| LLM Provider | 支持 OpenRouter 与 OpenAI 兼容接口 | - | 通过 `LLM_API_TYPE` 配置切换，便于对比不同模型。 |
| Libraries | 交易与数据处理依赖 python-binance、pandas、numpy 等 | 见 `requirements.txt` | 选用成熟生态中的主流库。 |

> 详细的项目结构与 PRD 映射见：`06-project-structure-and-mapping.md`；实现模式与版本策略见：`07-implementation-patterns.md`。

## 文档结构

- [1. 架构概览与部署](./01-overview-and-deployment.md)
- [2. 组件视图](./02-components.md)
- [3. 数据流](./03-data-flow.md)
- [4. 外部依赖与集成点](./04-integrations.md)
- [5. 可扩展性与演进建议](./05-evolution.md)
- [6. 项目结构与 PRD 映射](./06-project-structure-and-mapping.md)
- [7. 实现模式与一致性规则](./07-implementation-patterns.md)
