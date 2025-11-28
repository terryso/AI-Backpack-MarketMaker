#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Simple system prompt tuner for the DeepSeek Multi-Asset Trading Bot.

This script automates the following loop:

1. 根据一组结构化参数生成不同版本的 system prompt。
2. 通过环境变量 `BACKTEST_SYSTEM_PROMPT_FILE` 调用 `backtest.py`。
3. 读取 `backtest_results.json` 中的收益、Sortino、最大回撤等指标。
4. 为每个提示词配置计算一个综合评分，找出当前最优配置。

使用方式（在项目根目录执行，例如）：

    python scripts/auto_prompt_tuner.py \
        --start 2024-11-01T00:00:00Z \
        --end   2024-11-07T00:00:00Z \
        --interval 1h \
        --runs 6

注意：
- 每一次回测都会真实调用 LLM，成本和 `runs` × 时间跨度 × 周期有关；
- 建议先用较短时间 / 较长周期（例如 1h, 几天）做快速对比。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKTEST_DIR = PROJECT_ROOT / "data-backtest"
DEFAULT_BASE_PROMPT_PATH = PROJECT_ROOT / "prompts" / "system_prompt.txt"

INTERVAL_TO_SECONDS: Dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


def parse_iso8601_utc(value: str) -> datetime:
    """Parse a simple ISO8601 timestamp (with optional 'Z') into a datetime.

    我们只需粗略估算时间跨度用于计算 K 线数量，因此支持最常见格式：
    - 2024-11-01T00:00:00Z
    - 2024-11-01T00:00:00+00:00
    """

    text = value.strip()
    if not text:
        raise ValueError("empty datetime string")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


@dataclass
class PromptConfig:
    """Structured knobs that are injected into the system prompt.

    这些参数不会改变执行端硬风控（`execute_entry` 里的风控仍然生效），
    只是通过语言引导 LLM 更保守 / 激进、交易更频繁 / 稀疏等。
    """

    risk_profile: str
    trade_frequency: str
    tp_sl_style: str
    max_concurrent_positions: int


@dataclass
class BacktestMetrics:
    run_id: str
    start: str
    end: str
    interval: str
    total_return_pct: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown_pct: Optional[float]
    score: Optional[float]
    prompt_path: str
    config: PromptConfig


def load_base_prompt(path: Path = DEFAULT_BASE_PROMPT_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def build_system_prompt(base: str, cfg: PromptConfig) -> str:
    """Compose a full system prompt from base template + tuning config.

    这里我们采用“在原有规则后追加一段调优 profile”的方式，
    不去破坏你当前已经在用的 system_prompt.txt 内容。
    """

    tuning_block = f"""

---
[TRADING PROFILE TUNING]

- Risk profile: {cfg.risk_profile}
  - conservative: 优先保护本金，宁可错过机会也尽量避免大回撤。
  - balanced: 在风险和收益之间折中，允许适度 drawdown 换取收益。
  - aggressive: 追求更高收益，可以接受更大的浮亏和回撤。

- Trade frequency: {cfg.trade_frequency}
  - low: 只有在信号非常明显、性价比高时才下单，避免过度交易。
  - medium: 保持中等节奏，在合理机会出现时入场，但避免无意义频繁操作。
  - high: 更积极地寻找机会，但仍需严格遵守风险和仓位管理规则。

- Take-profit / Stop-loss style: {cfg.tp_sl_style}
  - tight: 止损距离相对较近，止盈也偏保守，整体偏短线、快进快出。
  - medium: 止盈止损距离适中，兼顾趋势跟随与风险控制。
  - wide: 止损/止盈区间更宽，适合趋势行情，但必须避免频繁加仓和梭哈。

- Max concurrent positions: {cfg.max_concurrent_positions}
  - 任何时刻，建议同时持有的币种仓位数量不要超过该值。
  - 如果已经达到上限，只能在平掉某些仓位之后再考虑新的 entry。

在生成交易决策（entry / close / hold）时，请严格遵守以上 profile 约束，
并在理由中体现出风险偏好、交易频率和止盈止损风格的考量。
"""

    base = base.rstrip()
    return f"{base}\n{tuning_block}\n" if base else tuning_block.lstrip("\n")


def sample_prompt_config() -> PromptConfig:
    risk_profile = "aggressive"
    trade_frequency = random.choice(["medium", "high"])
    tp_sl_style = random.choice(["medium", "wide"])
    max_concurrent_positions = random.choice([2, 3])
    return PromptConfig(
        risk_profile=risk_profile,
        trade_frequency=trade_frequency,
        tp_sl_style=tp_sl_style,
        max_concurrent_positions=max_concurrent_positions,
    )


def run_backtest_once(
    *,
    run_id: str,
    prompt_path: Path,
    start: str,
    end: str,
    interval: str,
    backtest_dir: Path,
    extra_env: Optional[Dict[str, str]] = None,
) -> Optional[BacktestMetrics]:
    env = os.environ.copy()

    env["BACKTEST_RUN_ID"] = run_id
    env["BACKTEST_SYSTEM_PROMPT_FILE"] = str(prompt_path)
    env.setdefault("BACKTEST_DATA_DIR", str(backtest_dir))
    env.setdefault("BACKTEST_DISABLE_TELEGRAM", "true")

    if start:
        env["BACKTEST_START"] = start
    if end:
        env["BACKTEST_END"] = end
    if interval:
        env["BACKTEST_INTERVAL"] = interval

    if extra_env:
        env.update(extra_env)

    print(f"[tuner] Running backtest for {run_id} ...", flush=True)
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "backtest.py")],
        env=env,
        cwd=str(PROJECT_ROOT),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if proc.returncode != 0:
        print(f"[tuner] Backtest {run_id} failed with code {proc.returncode}", flush=True)
        return None

    # Derive results path from BACKTEST_DATA_DIR + run_id.
    run_dir = backtest_dir / run_id
    results_path = run_dir / "backtest_results.json"
    if not results_path.exists():
        print(f"[tuner] Results file not found for {run_id}: {results_path}", flush=True)
        return None

    with results_path.open("r", encoding="utf-8") as fh:
        results = json.load(fh)

    capital = results.get("capital", {})
    total_return_pct = capital.get("total_return_pct")
    sortino_ratio = capital.get("sortino_ratio")
    max_drawdown_pct = capital.get("max_drawdown_pct")

    # Compute a simple score: prioritize stable Sortino with bounded drawdown.
    score = None
    if sortino_ratio is not None:
        try:
            sr = float(sortino_ratio)
            md = float(max_drawdown_pct) if max_drawdown_pct is not None else 0.0
            penalty = 0.0
            # Penalize very large drawdowns (over 40%).
            if md > 40.0:
                penalty += (md - 40.0) / 10.0
            score = sr - penalty
        except (TypeError, ValueError):  # pragma: no cover - defensive
            score = None

    # We will fill config later; caller knows the config.
    metrics = BacktestMetrics(
        run_id=run_id,
        start=results.get("timeframe", {}).get("start", start),
        end=results.get("timeframe", {}).get("end", end),
        interval=results.get("timeframe", {}).get("interval", interval),
        total_return_pct=float(total_return_pct) if total_return_pct is not None else None,
        sortino_ratio=float(sortino_ratio) if sortino_ratio is not None else None,
        max_drawdown_pct=float(max_drawdown_pct) if max_drawdown_pct is not None else None,
        score=score,
        prompt_path=str(prompt_path),
        config=PromptConfig("", "", "", 0),  # placeholder; caller will overwrite
    )
    return metrics


def write_results_csv(path: Path, rows: List[BacktestMetrics]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "run_id",
                "risk_profile",
                "trade_frequency",
                "tp_sl_style",
                "max_concurrent_positions",
                "start",
                "end",
                "interval",
                "total_return_pct",
                "sortino_ratio",
                "max_drawdown_pct",
                "score",
                "prompt_path",
            ]
        )
        for m in rows:
            writer.writerow(
                [
                    m.run_id,
                    m.config.risk_profile,
                    m.config.trade_frequency,
                    m.config.tp_sl_style,
                    m.config.max_concurrent_positions,
                    m.start,
                    m.end,
                    m.interval,
                    m.total_return_pct,
                    m.sortino_ratio,
                    m.max_drawdown_pct,
                    m.score,
                    m.prompt_path,
                ]
            )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-tune system prompt profiles by running multiple backtests "
            "with different risk/trade-frequency configurations."
        ),
    )
    parser.add_argument("--start", type=str, default="", help="BACKTEST_START (ISO8601, e.g. 2024-10-01T00:00:00Z)")
    parser.add_argument("--end", type=str, default="", help="BACKTEST_END (ISO8601)")
    parser.add_argument("--interval", type=str, default="15m", help="Backtest interval (default: 15m)")
    parser.add_argument("--runs", type=int, default=4, help="How many prompt configs to try (default: 4)")
    parser.add_argument(
        "--backtest-dir",
        type=str,
        default=str(DEFAULT_BACKTEST_DIR),
        help="BACKTEST_DATA_DIR for storing runs (default: data-backtest)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="tune",
        help="Prefix for BACKTEST_RUN_ID (default: tune)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="Override BACKTEST_LLM_MODEL for tuning runs (optional)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help=(
            "Comma-separated list of coins or symbols to backtest (e.g. BTC or BTC,ETH); "
            "forwarded to BACKTEST_SYMBOLS."
        ),
    )
    parser.add_argument(
        "--estimate-llm-calls",
        action="store_true",
        help=(
            "Only estimate how many LLM calls each backtest run would make based on "
            "start/end/interval, without actually running backtests."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    if args.estimate_llm_calls:
        if not args.start or not args.end:
            print("[tuner] --estimate-llm-calls requires both --start and --end.", flush=True)
            return

        try:
            start_dt = parse_iso8601_utc(args.start)
            end_dt = parse_iso8601_utc(args.end)
        except ValueError as exc:
            print(f"[tuner] Failed to parse start/end datetimes: {exc}", flush=True)
            return

        if start_dt >= end_dt:
            print("[tuner] BACKTEST_START must be earlier than BACKTEST_END", flush=True)
            return

        interval_key = args.interval.lower()
        if interval_key not in INTERVAL_TO_SECONDS:
            print(f"[tuner] Unsupported interval for estimation: {args.interval}", flush=True)
            return

        interval_seconds = INTERVAL_TO_SECONDS[interval_key]
        total_seconds = (end_dt - start_dt).total_seconds()
        if total_seconds < 0:
            print("[tuner] Negative timeframe duration; please check --start/--end.", flush=True)
            return

        # Approximate number of bars: floor(delta/interval) + 1
        bars_per_run = int(total_seconds // interval_seconds) + 1

        estimated_llm_per_run = bars_per_run
        estimated_llm_total = estimated_llm_per_run * args.runs

        print(
            f"[tuner] Timeframe {args.start} → {args.end} @ interval={args.interval}:",
            flush=True,
        )
        print(f"[tuner] Estimated bars per run: {bars_per_run}", flush=True)
        print(f"[tuner] Estimated LLM calls per run: {estimated_llm_per_run}", flush=True)
        print(
            f"[tuner] Estimated total LLM calls for {args.runs} runs: {estimated_llm_total}",
            flush=True,
        )
        return

    backtest_dir = Path(args.backtest_dir).expanduser().resolve()
    backtest_dir.mkdir(parents=True, exist_ok=True)

    base_prompt = load_base_prompt()
    if not base_prompt:
        print(f"[tuner] Warning: base system prompt not found at {DEFAULT_BASE_PROMPT_PATH}", flush=True)

    results: List[BacktestMetrics] = []
    best: Optional[BacktestMetrics] = None

    extra_env: Dict[str, str] = {}
    if args.model:
        extra_env["BACKTEST_LLM_MODEL"] = args.model
    if args.symbols:
        extra_env["BACKTEST_SYMBOLS"] = args.symbols

    timestamp_str = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    for i in range(1, args.runs + 1):
        cfg = sample_prompt_config()
        run_id = f"{args.prefix}-{timestamp_str}-{i}"

        prompt_text = build_system_prompt(base_prompt, cfg)
        prompt_dir = backtest_dir / "prompt_candidates"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompt_dir / f"{run_id}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        metrics = run_backtest_once(
            run_id=run_id,
            prompt_path=prompt_path,
            start=args.start,
            end=args.end,
            interval=args.interval,
            backtest_dir=backtest_dir,
            extra_env=extra_env,
        )
        if metrics is None:
            continue

        metrics.config = cfg
        results.append(metrics)

        if metrics.score is not None:
            if best is None or (best.score is None or metrics.score > best.score):
                best = metrics

        if metrics.total_return_pct is not None:
            return_str = f"{metrics.total_return_pct:.2f}%"
        else:
            return_str = "NA"

        print(
            f"[tuner] Finished {run_id}: return={return_str} "
            f"sortino={metrics.sortino_ratio} drawdown={metrics.max_drawdown_pct}% score={metrics.score}",
            flush=True,
        )

    if not results:
        print("[tuner] No successful backtest runs; nothing to write.", flush=True)
        return

    results_csv = backtest_dir / f"prompt_tuning_results_{timestamp_str}.csv"
    write_results_csv(results_csv, results)
    print(f"[tuner] Written tuning results to {results_csv}", flush=True)

    if best is not None:
        print("[tuner] Best config:")
        print(f"  run_id: {best.run_id}")
        print(f"  risk_profile: {best.config.risk_profile}")
        print(f"  trade_frequency: {best.config.trade_frequency}")
        print(f"  tp_sl_style: {best.config.tp_sl_style}")
        print(f"  max_concurrent_positions: {best.config.max_concurrent_positions}")
        print(f"  sortino_ratio: {best.sortino_ratio}")
        print(f"  max_drawdown_pct: {best.max_drawdown_pct}")
        print(f"  total_return_pct: {best.total_return_pct}")
        print(f"  score: {best.score}")
        print(f"  prompt_path: {best.prompt_path}")
    else:
        print("[tuner] No best config (no scores computed).", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
