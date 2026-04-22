# Framework Strategy Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In one execution pass, remove the remaining framework-layer `Strategy*` / `strategy_*` naming from app, workers, runtime wiring, tests, and docs while keeping `src/strategies/current/` strategy-module naming intact.

**Architecture:** Treat "strategy" as an extension/business-module concept, not a framework service/worker concept. Framework app code should expose trading decision planning names; worker/runtime code should expose trading decision worker names. Do not keep compatibility aliases, duplicate modules, or wrapper imports for the old names.

**Tech Stack:** Python dataclasses, pytest, ruff, git file renames.

---

## Scope

This is a single-round refactor. It includes the already-started `AuditEvent` small residual cleanup and the complete framework-level rename. It does not rename `src/strategies/current/CurrentStrategy`, `CurrentStrategyConfig`, or strategy package tests that refer to the actual example strategy.

## Rename Map

- `src/polymarket_trader/app/strategy_entry_plan.py` -> `src/polymarket_trader/app/entry_plan.py`
- `StrategyEntryPlan` -> `EntryPlan`
- `src/polymarket_trader/app/strategy_entry_planner.py` -> `src/polymarket_trader/app/entry_planner.py`
- `StrategyEntryPlanner` -> `EntryPlanner`
- `src/polymarket_trader/app/strategy_service.py` -> `src/polymarket_trader/app/trading_decision_service.py`
- `StrategyService` -> `TradingDecisionService`
- `src/polymarket_trader/workers/strategy_worker.py` -> `src/polymarket_trader/workers/trading_decision_worker.py`
- `StrategyWorker` -> `TradingDecisionWorker`
- `src/polymarket_trader/workers/strategy_worker_result.py` -> `src/polymarket_trader/workers/trading_decision_worker_result.py`
- `StrategyWorkerResult` -> `TradingDecisionWorkerResult`
- `src/polymarket_trader/workers/strategy_event_payloads.py` -> `src/polymarket_trader/workers/trading_decision_event_payloads.py`
- `STRATEGY_WORKER_ORIGIN` -> `TRADING_DECISION_WORKER_ORIGIN`
- origin value `"strategy_worker"` -> `"trading_decision_worker"`
- `src/polymarket_trader/workers/strategy_order_result_processor.py` -> `src/polymarket_trader/workers/trading_order_result_processor.py`
- `StrategyOrderResultProcessor` -> `TradingOrderResultProcessor`
- runtime field `strategy_service` -> `trading_decision_service`
- runtime field `strategy_worker` -> `trading_decision_worker`
- trace id fallback `"strategy-replay"` -> `"extension-replay"`
- `tests/app/test_strategy_service.py` -> `tests/app/test_trading_decision_service.py`
- `tests/strategies/current/test_strategy_worker_integration.py` -> `tests/strategies/current/test_trading_decision_worker_integration.py`

## Task 1: Keep AuditEvent Small Residual Cleanup

**Files:**
- Modify: `src/polymarket_trader/domain/events.py`
- Modify: `tests/domain/test_events.py`

- [ ] Confirm `AuditEvent` no longer has a dedicated `legacy_event_type` branch.
- [ ] Confirm `tests/domain/test_events.py` expects `AuditEvent(event_type=..., trace_id=...)` to fail with `AuditEvent requires event_title`.
- [ ] Run:

```bash
pytest -q tests/domain/test_events.py
```

Expected: all tests in `tests/domain/test_events.py` pass.

## Task 2: Rename App-Level Decision Planning Surface

**Files:**
- Move: `src/polymarket_trader/app/strategy_entry_plan.py` -> `src/polymarket_trader/app/entry_plan.py`
- Move: `src/polymarket_trader/app/strategy_entry_planner.py` -> `src/polymarket_trader/app/entry_planner.py`
- Move: `src/polymarket_trader/app/strategy_service.py` -> `src/polymarket_trader/app/trading_decision_service.py`
- Modify: `src/polymarket_trader/app/reconcile_service.py`
- Modify: `src/polymarket_trader/app/extension_host/replay.py`
- Move: `tests/app/test_strategy_service.py` -> `tests/app/test_trading_decision_service.py`

- [ ] Update tests first:
  - import `TradingDecisionService` from `polymarket_trader.app.trading_decision_service`;
  - rename test names from `test_strategy_service_*` to `test_trading_decision_service_*`;
  - keep behavior assertions unchanged.
- [ ] Run:

```bash
pytest -q tests/app/test_trading_decision_service.py
```

Expected before implementation: import failure for missing `polymarket_trader.app.trading_decision_service`.

- [ ] Move files with `git mv` using the rename map above.
- [ ] Rename classes and imports:
  - `StrategyEntryPlan` -> `EntryPlan`;
  - `StrategyEntryPlanner` -> `EntryPlanner`;
  - `StrategyService` -> `TradingDecisionService`.
- [ ] Keep `decision_to_managed_intent` name unchanged unless code context requires a local import update; it is not a strategy-specific name.
- [ ] In `extension_host/replay.py`, use `TradingDecisionService`, `EntryPlan`, and fallback trace id `"extension-replay"`.
- [ ] Run:

```bash
pytest -q tests/app/test_trading_decision_service.py tests/app/extension_host/test_replay.py
```

Expected: pass.

## Task 3: Rename Worker and Runtime Wiring

**Files:**
- Move: `src/polymarket_trader/workers/strategy_worker.py` -> `src/polymarket_trader/workers/trading_decision_worker.py`
- Move: `src/polymarket_trader/workers/strategy_worker_result.py` -> `src/polymarket_trader/workers/trading_decision_worker_result.py`
- Move: `src/polymarket_trader/workers/strategy_event_payloads.py` -> `src/polymarket_trader/workers/trading_decision_event_payloads.py`
- Move: `src/polymarket_trader/workers/strategy_order_result_processor.py` -> `src/polymarket_trader/workers/trading_order_result_processor.py`
- Modify: `src/polymarket_trader/main.py`
- Modify: `tests/app/test_runtime.py`
- Move: `tests/strategies/current/test_strategy_worker_integration.py` -> `tests/strategies/current/test_trading_decision_worker_integration.py`

- [ ] Update tests first:
  - import `TradingDecisionWorker` from `polymarket_trader.workers.trading_decision_worker`;
  - import `TradingDecisionService` from `polymarket_trader.app.trading_decision_service`;
  - rename local variables `strategy_service` / `strategy_worker` to `trading_decision_service` / `trading_decision_worker`;
  - update runtime assertions to `runtime.trading_decision_service` and `runtime.trading_decision_worker`.
- [ ] Run:

```bash
pytest -q tests/app/test_runtime.py tests/strategies/current/test_trading_decision_worker_integration.py
```

Expected before implementation: import or attribute failures for new worker/runtime names.

- [ ] Move worker files with `git mv`.
- [ ] Rename classes and constants:
  - `StrategyWorker` -> `TradingDecisionWorker`;
  - `StrategyWorkerResult` -> `TradingDecisionWorkerResult`;
  - `StrategyOrderResultProcessor` -> `TradingOrderResultProcessor`;
  - `STRATEGY_WORKER_ORIGIN` -> `TRADING_DECISION_WORKER_ORIGIN`;
  - `is_from_strategy_worker` -> `is_from_trading_decision_worker`.
- [ ] Rename constructor arguments and attributes:
  - `strategy_service` -> `trading_decision_service`;
  - `_strategy_service` -> `_trading_decision_service`.
- [ ] In `main.py`, update imports, `Runtime` dataclass fields, local variables, worker construction, supervisor runner, and any object wiring.
- [ ] Do not keep old runtime fields as aliases.
- [ ] Run:

```bash
pytest -q tests/app/test_runtime.py tests/strategies/current/test_trading_decision_worker_integration.py tests/app/test_trading_decision_service.py
```

Expected: pass.

## Task 4: Update Docs and README Contracts

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/设计文档.md`
- Modify: `docs/需求文档.md`
- Modify: `src/polymarket_trader/app/README.md`
- Modify: `src/polymarket_trader/workers/README.md`

- [ ] Update the trading chain in `AGENTS.md` and app README to:

```text
event -> TradingDecisionWorker -> TradingDecisionService -> PortfolioAllocator -> RiskManager -> TradingService -> OrderExecutor -> outbox/audit
```

- [ ] Replace framework references:
  - `StrategyService` -> `TradingDecisionService`;
  - `StrategyWorker` -> `TradingDecisionWorker`;
  - `strategy_service.py` -> `trading_decision_service.py`;
  - `strategy_worker.py` -> `trading_decision_worker.py`.
- [ ] Keep `src/strategies/current/` and `CurrentStrategy` references when they describe the actual example strategy module.

## Task 5: Residual Scan and Verification

**Files:**
- All files changed in Tasks 1-4.

- [ ] Run the old framework-name scan:

```bash
rg -n "\bStrategy(Service|Worker|Entry|EntryPlan|EntryPlanner|WorkerResult|OrderResultProcessor)|strategy_(service|worker|entry|entry_plan|entry_planner|event_payloads|worker_result|order_result_processor)|STRATEGY_WORKER_ORIGIN|strategy-replay" src/polymarket_trader tests docs README.md AGENTS.md
```

Expected: no results except references under `src/strategies/current/` or strategy-specific test names that refer to the actual example strategy. If any result is in `src/polymarket_trader/app`, `src/polymarket_trader/workers`, `src/polymarket_trader/main.py`, `AGENTS.md`, or generic docs, update it.

- [ ] Run broad verification:

```bash
ruff check src tests && pytest -q
```

Expected: `All checks passed!` and all pytest tests pass with the existing skipped count.

- [ ] Check worktree:

```bash
git status --short
git diff --stat
```

Expected: only files in this plan are modified/moved.

## Task 6: Commit

**Files:**
- All modified, moved, and deleted files from this plan.

- [ ] Commit the one-round refactor:

```bash
git add -A
git commit -m "refactor: rename framework strategy pipeline"
```

- [ ] Confirm clean state:

```bash
git status --short
git log -1 --oneline
```

Expected: clean status and a latest commit with message `refactor: rename framework strategy pipeline`.
