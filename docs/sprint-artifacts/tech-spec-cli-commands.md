# Tech-Spec: 为 Telegram 逻辑增加 CLI 入口

**Created:** 2025-12-05  
**Status:** ✅ Implemented

---

## Overview

### Problem Statement

- 目前所有「控制 / 查询 Bot 状态」的操作都通过 Telegram Bot 命令完成。  
- 当在本机开发 / 调试时，用 Telegram 远程发指令效率较低；直接在终端运行命令（CLI）更自然、更快捷。  
- 项目已经有一套较完善的 Telegram 命令体系，希望 **CLI 完全复用这套逻辑**，避免重复实现和行为漂移。

### Solution

- 在 `notifications.commands` 现有架构基础上，新增一层 **CLI 适配层**：
  - **输入侧**：使用 Click 框架，将命令行参数映射为 Telegram 风格命令
  - **业务侧**：直接调用现有 `handle_*_command` 函数
  - **输出侧**：将 `CommandResult.message` 从 MarkdownV2 转成终端友好文本

---

## Implementation

### Files Created

- `cli/__init__.py` - CLI 模块初始化
- `cli/main.py` - Click 命令组和所有子命令定义
- `cli/context.py` - CLI 上下文构建（状态加载、交易所连接等）
- `cli/output.py` - 输出格式化（MarkdownV2 → 终端文本）
- `llm_trader.py` - 顶层入口脚本
- `scripts/llm-trader` - Shell wrapper 脚本

### Dependencies Added

- `click>=8.0.0` (added to requirements.txt)

### Command Mapping

| CLI 命令 | Telegram 命令 | 说明 |
|---------|--------------|------|
| `llm-trader status` | `/status` | 查看 Bot 资金与盈利状态 |
| `llm-trader balance` | `/balance` | 查看当前账户余额与持仓概要 |
| `llm-trader positions` | `/positions` | 查看当前所有持仓详情 |
| `llm-trader kill` | `/kill` | 激活 Kill-Switch |
| `llm-trader resume` | `/resume` | 解除 Kill-Switch |
| `llm-trader risk` | `/risk` | 查看风控配置与状态 |
| `llm-trader reset-daily` | `/reset_daily` | 重置每日亏损基准 |
| `llm-trader close SYMBOL [AMOUNT]` | `/close SYMBOL [AMOUNT]` | 平仓 |
| `llm-trader close-all [DIRECTION]` | `/close_all [long\|short]` | 全平 |
| `llm-trader sl SYMBOL VALUE` | `/sl SYMBOL VALUE` | 设置止损 |
| `llm-trader tp SYMBOL VALUE` | `/tp SYMBOL VALUE` | 设置止盈 |
| `llm-trader tpsl SYMBOL SL TP` | `/tpsl SYMBOL SL TP` | 设置止损止盈 |
| `llm-trader config list` | `/config list` | 列出配置项 |
| `llm-trader config get KEY` | `/config get KEY` | 查看配置 |
| `llm-trader config set KEY VALUE` | `/config set KEY VALUE` | 修改配置 |
| `llm-trader symbols list` | `/symbols list` | 查看 Universe |
| `llm-trader symbols add SYMBOL` | `/symbols add SYMBOL` | 添加交易对 |
| `llm-trader symbols remove SYMBOL` | `/symbols remove SYMBOL` | 移除交易对 |
| `llm-trader audit [START] [END]` | `/audit [START] [END]` | 资金变动分析 |
| `llm-trader help` | `/help` | 显示帮助 |

---

## Usage

### 直接运行

```bash
# 使用 Python 入口
python llm_trader.py <command> [args...]

# 或使用 shell wrapper
./scripts/llm-trader <command> [args...]
```

### 示例

```bash
# 查看状态
python llm_trader.py status
python llm_trader.py balance
python llm_trader.py positions

# 风控操作
python llm_trader.py kill
python llm_trader.py resume
python llm_trader.py risk

# 平仓操作
python llm_trader.py close BTC
python llm_trader.py close BTC 50
python llm_trader.py close-all

# 止损止盈
python llm_trader.py sl BTC -5%
python llm_trader.py tp BTC 10%
python llm_trader.py tpsl BTC -5% 10%

# 配置管理
python llm_trader.py config list
python llm_trader.py config get TRADEBOT_INTERVAL
python llm_trader.py config set TRADEBOT_INTERVAL 5m

# Universe 管理
python llm_trader.py symbols list
python llm_trader.py symbols add BTCUSDT
python llm_trader.py symbols remove SOLUSDT

# 资金审计
python llm_trader.py audit
python llm_trader.py audit 09:00
python llm_trader.py audit 09:00 18:00

# 帮助
python llm_trader.py --help
python llm_trader.py config --help
```

### 详细日志

```bash
python llm_trader.py -v status
```

---

## Architecture

```
CLI Layer (cli/main.py)
    │
    ├── Click command parsing
    │
    ├── Build TelegramCommand
    │
    └── Call handle_*_command()
            │
            ├── notifications/commands/*.py (业务逻辑)
            │
            └── Return CommandResult
                    │
                    └── cli/output.py (格式化输出)
```

### Key Design Decisions

1. **复用 TelegramCommand / CommandResult**  
   CLI 不引入新的 Command 类型，直接创建 `TelegramCommand` 实例，所有现有 `handle_*_command` 代码完全复用。

2. **状态获取策略**  
   - 优先使用实盘交易所快照
   - 回退到本地 `portfolio_state.json`
   - 风控状态修改后自动持久化

3. **输出格式化**  
   - 去除 MarkdownV2 转义字符
   - 保留 emoji（终端一般支持）
   - 保留 backtick 代码标记

---

## Testing

运行单元测试：

```bash
./scripts/run_tests.sh
```

CLI 相关测试可以通过以下方式验证：

```bash
# 基础功能测试
python llm_trader.py --help
python llm_trader.py config list
python llm_trader.py symbols list
python llm_trader.py help
```
