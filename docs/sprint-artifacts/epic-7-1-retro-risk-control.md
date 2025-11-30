# Epic 7.1 回顾：风控状态管理基础设施

## 1. Epic 概览

- **Epic ID**: 7-1 – 风控状态管理基础设施
- **完成 Story**：
  - 7-1-1 定义 `RiskControlState` 数据结构
  - 7-1-2 添加风控相关环境变量
  - 7-1-3 实现风控状态持久化
  - 7-1-4 集成风控状态到主循环
- **总体目标**：为后续 Kill-Switch（Epic 7.2）、每日亏损限制（Epic 7.3）和 Telegram 控制（Epic 7.4）提供可靠的风控状态模型、配置入口、持久化机制和主循环集成点。

## 2. 做得好的地方（What Went Well）

- **2.1 分层清晰，职责边界明确**
  - `core/risk_control.py` 专注于风控状态结构与序列化（7-1-1）。
  - `config/settings.py` 集中管理风控配置，包含解析与范围校验（7-1-2）。
  - `core/state.py` 负责运行时全局状态协调，同时读写 `risk_control` 字段（7-1-3）。
  - `bot.py` 仅通过 `core.state` 与 `check_risk_limits()` 进行集成（7-1-4），没有直接操作 JSON 或环境变量。

- **2.2 状态持久化设计健壮，充分考虑兼容性与完整性**
  - `portfolio_state.json` 顶层结构扩展为包含 `risk_control` 字段，结构与 `RiskControlState.to_dict()` 对齐。
  - `core/state.load_state()` 对以下情况都有明确处理与日志：
    - 文件不存在 → 使用安全默认值。
    - JSON 损坏或结构异常 → 回退默认状态并记录 ERROR。
    - `risk_control` 缺失或类型错误 → 使用默认 `RiskControlState()` 并记录 INFO/WARN。
  - `core/persistence.save_state_to_json()` 采用 **原子写入**（写 .tmp，再 `Path.replace()`），满足 PRD NFR 对状态完整性的要求。

- **2.3 配置与行为可控，默认安全（Secure by Default）**
  - `RISK_CONTROL_ENABLED=True`、`DAILY_LOSS_LIMIT_ENABLED=True`、`DAILY_LOSS_LIMIT_PCT=5.0`、`KILL_SWITCH=False` 提供了保守且安全的默认配置。
  - `_parse_float_env_with_range()` 提供统一的范围校验与 warning 行为，避免危险阈值导致意外风险暴露。
  - `.env.example` 补充了中文说明与风险提示，降低误用概率。

- **2.4 测试覆盖全面，集成场景拉通**
  - `tests/test_risk_control.py` 覆盖 `RiskControlState` 的默认值、序列化/反序列化与缺失字段处理。
  - `tests/test_risk_control_config.py` 覆盖风控配置的默认值、环境变量覆盖和非法输入回退。
  - `tests/test_risk_control_integration.py` 覆盖：
    - `risk_control` 字段持久化与恢复。
    - 旧 JSON（无 `risk_control`）兼容路径。
    - 原子写入失败不破坏原有状态文件。
    - `check_risk_limits()` 入口行为与日志。
    - 模拟多次迭代后重启，风控状态保持一致。
  - `tests/test_state_management.py` 已更新，与 `core.state` 的统一入口保持一致。
  - 全局共有 **420 个测试全部通过**，确保对现有行为没有回归。

- **2.5 主循环集成点合理，为后续能力留足扩展空间**
  - 在 `_run_iteration()` 中，风控检查位于：
    - 日志 Header 之后；
    - 市场数据拉取与 LLM 调用之前；
    - 且仍在 `core/` 层控制（`core.risk_control.check_risk_limits()`）。
  - `check_risk_limits()` 预留了 `total_equity` 与 `iteration_time` 参数，后续 Epic 7.2/7.3 可以直接接入，而无需再改动主循环调用点。

## 3. 可以改进的地方（What Didn’t Go Well / Challenges）

- **3.1 bot 与 core.state 之间的状态同步心智负担较大**
  - 历史原因导致 `bot.py` 仍保留 `balance` / `positions` / `iteration_counter` 的模块级变量，为了兼容既有测试与调用方，这些变量需要与 `core.state` 中的全局状态保持同步。
  - 在 7-1-4 中，通过 `load_state()` / `save_state()` 把同步逻辑集中化，但开发与测试过程中仍需要时刻注意「单一真实来源」是 `core.state`。
  - `tests/test_state_management.py` 需要更新才能正确 mock `core.state.STATE_JSON`，暴露出历史架构决定带来的耦合成本。

- **3.2 少量实现细节存在可以打磨的地方**
  - `core/risk_control.py` 中的 `TYPE_CHECKING` 分支引用了自身模块的类型别名，这在当前实现中并无必要，稍微增加了阅读噪音（已在 Story 7.1.4 的 Review 中标记为 Low 级别建议）。
  - 风控相关日志目前分布在 `core.state` 与 `bot.py` 中（启动时输出配置摘要 + 状态摘要），后续可以考虑统一风格与字段顺序，提升可观测性的一致性。

- **3.3 风控配置与持久化状态的优先级策略尚未在代码层完全固化**
  - Tech Spec 与 Dev Notes 中已提到「环境变量优先于持久化状态」的原则，例如：
    - 当 `KILL_SWITCH=true`（环境变量）但状态文件中记录为关闭时，应以环境变量为准。
  - 当前 Epic 7.1 主要完成了**状态与配置的基础设施**，实际的优先级逻辑与 Kill-Switch 具体行为计划在 Epic 7.2 实现。
  - 这意味着在实际启用 Kill-Switch / 每日亏损限制前，仍需要一次统一的行为设计与实现，避免出现「配置与状态不一致」的边缘情况。

## 4. 关键经验与教训（Key Learnings）

- **4.1 先统一状态入口，再做功能集成，成本更低**
  - 先通过 7-1-3 把所有状态持久化路径收敛到 `core.state` / `core.persistence`，再在 7-1-4 中在主循环接入风控逻辑，避免了在多个 JSON 读写路径上分别补齐 `risk_control` 字段的重复工作。

- **4.2 配置、状态与行为三层分离是健康的设计边界**
  - 配置层：`config/settings.py` + `.env.example`，负责「用户如何开启/关闭/调优风控」。
  - 状态层：`RiskControlState` + `core.state` + `core.persistence`，负责「当前/历史风控状态如何存储」。
  - 行为层：`check_risk_limits()` + 主循环集成点，负责「在一次迭代中如何基于状态与配置做决策」。
  - 这种分层让后续实现 Kill-Switch、每日亏损限制和 Telegram 命令时，可以在行为层演进，而无需反复触碰配置与持久化层。

- **4.3 集成测试对风控类功能尤为关键**
  - 单元测试可以验证 `RiskControlState` 和配置解析的正确性，但真实风险在于「重启后是否还能恢复到安全状态」。
  - `tests/test_risk_control_integration.py` 模拟多次迭代 + 重启，验证 `risk_control` 字段的前后兼容性和持久化行为，对提升信任度非常有效。

- **4.4 提前为后续 Epic 预留接口是值得的投资**
  - 目前 `check_risk_limits()` 只是一个占位实现（始终返回 True），但已经具备完整签名与日志：
    - 后续只需在函数内部增加 Kill-Switch 与每日亏损逻辑即可，无需大改调用方。
  - `RiskControlState` 已包含 Kill-Switch 与每日亏损相关字段，无需在 Epic 7.2/7.3 再做 schema 变更。

## 5. 对后续 Epic（7.2–7.4）的影响与准备

- **Epic 7.2 – Kill-Switch 核心功能**
  - 依赖：
    - `RiskControlState.kill_switch_active / reason / triggered_at / daily_loss_triggered`。
    - `check_risk_limits()` 入口 + `RISK_CONTROL_ENABLED`/`KILL_SWITCH` 配置。
  - 准备情况：
    - 基础设施已就绪，可在 `check_risk_limits()` 内直接实现：
      - 基于环境变量或状态决定是否 Block 新开仓。
      - 更新 Kill-Switch 相关字段并写入状态文件。

- **Epic 7.3 – 每日亏损限制功能**
  - 依赖：
    - `RiskControlState.daily_start_equity / daily_start_date / daily_loss_pct`。
    - `DAILY_LOSS_LIMIT_ENABLED` / `DAILY_LOSS_LIMIT_PCT` 配置。
    - 每次迭代时可获取 `total_equity` 与 `iteration_time`（已在 `check_risk_limits()` 参数中预留）。
  - 准备情况：
    - 可在每次迭代开始时：
      - 根据 `iteration_time` 判断是否跨日，必要时重置 `daily_start_equity`。
      - 根据 `total_equity` 计算 `daily_loss_pct`，与 `DAILY_LOSS_LIMIT_PCT` 对比并更新状态。

- **Epic 7.4 – Telegram 命令集成**
  - 依赖：
    - 已持久化并可恢复的 `RiskControlState`。
    - 主循环中已经存在的 Kill-Switch / 日亏损逻辑接口（未来在 7.2/7.3 中实现）。
  - 准备情况：
    - Telegram 命令可以通过读取与修改 `RiskControlState` 来实现 `kill` / `resume` / `status` / `reset-daily` 等命令，而无需新增状态存储结构。

## 6. Action Items（行动项）

> 说明：以下为建议性改进项，优先级可在规划 Epic 7.2 / 7.3 / 7.4 时统一评估。

### 6.1 Code / Design

- [ ] **[Medium] 明确并实现「环境变量 vs. 持久化状态」的优先级规则**  
  - **描述**：在 Epic 7.2 中补齐环境变量（特别是 `KILL_SWITCH`）与持久化状态之间的冲突解决策略，例如：环境层显式开启 Kill-Switch 时，始终覆盖状态文件中的关闭标记。  
  - **相关文件**：`config/settings.py`, `core/state.py`, `core/risk_control.py`（未来逻辑）。

- [ ] **[Low] 清理风控模块中不必要的 TYPE_CHECKING 引用**  
  - **描述**：移除 `core/risk_control.py` 中对自身模块的 `TYPE_CHECKING` 引用，保持类型声明简洁。  
  - **相关文件**：`core/risk_control.py`。

### 6.2 Process / Practice

- [ ] **[Low] 在后续 Story 中统一「风控相关日志格式与位置」**  
  - **描述**：梳理启动、迭代和异常路径中与风控相关的日志，在字段顺序、日志级别和消息前缀上形成统一规范，便于后续排错与可观测性建设。  
  - **相关文件**：`core/state.py`, `bot.py`, 未来的 Kill-Switch / 日亏损逻辑实现。

---

**结论**：Epic 7.1 已完整交付风控基础设施（数据结构、配置、持久化与主循环集成），为后续 Epic 7.2–7.4 提供了稳固的技术基座。后续工作应聚焦在具体风控策略（Kill-Switch / 每日亏损）和外部控制接口（Telegram 命令）的业务逻辑上，同时落实少量行为优先级和可观测性方面的改进。
