# Extension API Refactor Design

Date: 2026-04-22

## Goal

Turn the project from a single-business trading bot into a reusable secondary-development framework.
The framework must keep the trading runtime, state management, external adapters, risk gate, order execution,
audit, persistence, API, and worker orchestration generic. All business-specific behavior must live in a
business extension package such as `src/strategies/current/`, or be expressed through hooks, decisions, and
commands returned by that extension.

The target extension model is not a minimal strategy interface. Future business logic is unknown, so the
framework should expose broad read capabilities and many lifecycle intervention points. At the same time,
real side effects must remain controlled by the framework so business extensions cannot bypass risk,
queue priority, audit, or reconciliation guarantees.

Core rule:

```text
wide read access
many hook points
narrow write access
framework-owned side effects
```

## Non-Goals

- Do not let business extensions directly call `OrderExecutor`, SQLAlchemy repositories, runtime hot-state
  write locks, or raw Polymarket SDK clients.
- Do not keep FDV, threshold, keyword, primary outcome, YES/NO trading policy, equal-weight allocation, or
  current-strategy recovery semantics in framework modules.
- Do not add long-term compatibility aliases for old strategy names or duplicate business fields in the
  framework.
- Do not introduce a second trading path. All orders still pass through risk review, trading service,
  order executor, outbox, and audit.

## Recommended Shape

Rename and broaden the public secondary-development contract from the legacy strategy SDK package to:

```text
src/polymarket_trader/extension_api/
```

This package is the only stable public API that business extensions should import from the framework.
It should include:

```text
extension_api/
  __init__.py
  manifest.py      # extension identity, factory, capabilities, config type
  context.py       # read-only runtime contexts passed into hooks
  ports.py         # broad read ports and telemetry/clock ports
  hooks.py         # lifecycle hook protocol
  decisions.py     # market, allocation, entry, exit, follow-up, recovery decisions
  commands.py      # controlled framework commands requested by extensions
  events.py        # observable hook/event DTOs exposed to extensions
```

The current business implementation should become an ordinary extension package:

```text
src/strategies/current/
  manifest.py
  config.py
  discovery.py
  universe.py
  outcomes.py
  allocation.py
  entry.py
  exit.py
  followup.py
  recovery.py
  tracking.py
  hooks.py
```

`strategies/current` may keep FDV defaults, target outcome selection, price thresholds, liquidity thresholds,
equal-weight allocation, post-fill sell logic, filtered-market retention, and recovery policy. Framework
modules must treat those as extension output, not built-in truth.

## Public Extension Contract

An extension is loaded from a manifest and factory:

```python
class ExtensionManifest:
    name: str
    version: str
    module_path: str
    factory: ExtensionFactory
    config_type: type | None
    capabilities: tuple[str, ...]
```

The factory receives framework-provided ports and an optional config path, then returns an extension object:

```python
class BusinessExtension:
    @property
    def manifest(self) -> ExtensionManifest: ...
    @property
    def hooks(self) -> ExtensionHooks: ...
```

The extension object may be implemented as one class or composed from modules. The framework should only
depend on the protocol, not on `strategies.current` internals.

## Broad Read Ports

Ports should be broad enough for unknown future business logic, but read-oriented by default:

- `MarketReadPort`: get/list tracked markets, lookup by condition, token, slug, read market metadata.
- `OrderbookReadPort`: get current and recent orderbook snapshots by token.
- `AccountReadPort`: read balance, allowance, positions, open orders, paused markets, last reconcile state.
- `HistoryReadPort`: read recent fills, orders, audit events, and snapshots within bounded query limits.
- `RuntimeReadPort`: read queue depths, worker status, reconcile status, trading readiness, runtime pauses.
- `ConfigReadPort`: read sanitized framework config and extension config metadata.
- `TelemetryPort`: record metrics and structured extension observations.
- `ClockPort`: get framework time for deterministic tests.

Ports must avoid exposing mutable runtime objects directly. Returned values should be immutable DTOs,
snapshots, or read-only protocol views. Expensive history queries need explicit bounds and timeout behavior.

## Controlled Commands

Extensions can request framework side effects by returning commands. They do not execute side effects
directly.

Initial command set:

- `PauseMarketCommand`
- `ResumeMarketCommand`
- `PauseEntriesCommand`
- `TriggerReconcileCommand`
- `RefreshMarketCommand`
- `EmitAlertCommand`
- `RecordAuditCommand`
- `SubscribeMarketCommand`
- `UnsubscribeMarketCommand`

Command execution remains framework-owned. The framework validates the command, schedules it on the right
queue, emits audit/outbox events, and exposes command results through runtime snapshots.

Trading commands remain decisions or intents, not direct executor calls:

```text
BuyDecision / SellDecision / CancelDecision / ReplaceDecision
  -> RiskManager
  -> TradingService
  -> OrderExecutor
  -> outbox/audit
```

## Lifecycle Hooks

The framework should expose lifecycle hooks at stable orchestration points. Hooks may return decisions,
commands, metadata patches, or no-op results. They must not block the P0 trading path with slow I/O.

Recommended hook groups:

- Discovery:
  - `build_discovery_queries`
  - `before_market_parse`
  - `after_market_parse`
  - `select_market`
  - `on_market_discovered`
  - `on_market_filtered`
  - `should_keep_tracking`
  - `build_filtered_tracking_market`

- Market data:
  - `on_orderbook_snapshot`
  - `on_market_status_change`
  - `build_entry_candidates`

- Allocation and trading:
  - `allocate`
  - `before_entry_decision`
  - `decide_entry`
  - `decide_exit`
  - `decide_follow_up`
  - `before_risk_check`
  - `after_risk_reject`
  - `before_order_submit`
  - `after_order_submit`
  - `on_order_result`
  - `on_fill`

- Reconcile and recovery:
  - `on_reconcile_started`
  - `on_reconcile_snapshot`
  - `decide_recovery`
  - `on_reconcile_finished`

- Admin and observability:
  - `build_admin_market_view`
  - `build_admin_runtime_view`
  - `on_runtime_warning`
  - `on_extension_error`

Hooks should use explicit context types, for example `DiscoveryContext`, `MarketContext`,
`TradingContext`, `OrderResultContext`, `ReconcileContext`, and `AdminViewContext`.

## Framework Boundaries

Framework modules keep these responsibilities:

- `domain`: generic domain models and invariant rules only. No current-strategy thresholds, keywords,
  outcome preference, or allocation policy.
- `app`: generic use-case orchestration. It calls extension hooks and translates extension decisions into
  framework intents, but does not encode business semantics.
- `runtime`: queues, hot state, registry, supervisor, scheduler, and snapshots. Extensions read through
  ports and request changes through commands.
- `infra`: external protocol adapters. Raw external payloads become internal DTOs before entering app code.
- `api`: validation, service calls, response serialization, and admin-controlled operations. No direct
  trading client calls.
- `workers`: message transport and scheduling. No copied strategy or discovery business rules.

## Current Code Migration Targets

Move or rename the current business leftovers:

- Replace the legacy strategy SDK package with `src/polymarket_trader/extension_api/`, with compatibility avoided unless there
  is an explicit external contract.
- Old runtime module defaults -> explicit extension module configuration with no
  business default embedded in framework policy. Example deployments may still configure `strategies.current`.
- `domain/classifier.py` -> generic market payload parsing under app/infra naming, such as
  `MarketPayloadParser`. It should parse required trading fields but not imply business classification.
- `domain/allocation.py` -> split generic allocation DTOs from equal-weight allocation. Equal-weight logic
  moves to `strategies/current/allocation.py`.
- Framework references to current strategy reasons such as `strategy_filtered_out`, `strategy_entry`,
  and `strategy_exit` should become extension-provided strings that the framework records and propagates.
- Outcome fallback like default `YES`/`NO` names may remain as a Polymarket payload normalization behavior
  only where the external protocol actually implies it. Target outcome preference belongs in the extension.

## Data Flow

Discovery flow:

```text
extension.build_discovery_queries
  -> framework fetches raw markets
  -> framework parses raw payload to generic market candidate
  -> extension.select_market
  -> registry/tracker update
  -> extension retention hooks if filtered
  -> audit/outbox
```

Trading flow:

```text
market/orderbook event
  -> framework builds trading context from registry, orderbook, account, and ports
  -> extension.build_entry_candidates
  -> extension.allocate
  -> extension.decide_entry / decide_exit / decide_follow_up
  -> framework converts decision to order intent
  -> RiskManager
  -> TradingService
  -> OrderExecutor
  -> outbox/audit
  -> extension.on_order_result / on_fill
```

Recovery flow:

```text
reconcile trigger
  -> framework gathers authoritative snapshots
  -> extension.on_reconcile_snapshot
  -> extension.decide_recovery
  -> framework executes returned commands/intents through normal gates
  -> audit/outbox/status snapshot
```

## Error Handling

- Hook exceptions must be captured as extension errors with trace IDs, hook names, and sanitized context.
- P0 trading hooks should fail closed for trade creation: no trade if the extension decision hook errors.
- Non-critical hooks should degrade to no-op and emit warning/audit events.
- Slow hooks need timeouts. Timeout policy should be per hook group, with stricter limits on trading hooks.
- Command execution failures should be recorded as command results and exposed through admin/runtime snapshots.

## Testing Strategy

Tests should prove both framework neutrality and extension power:

- Framework modules must not import `strategies.current` except extension loading tests or example runtime
  wiring.
- A fake extension can implement discovery, allocation, trading, follow-up, recovery, and commands without
  depending on current FDV code.
- Current FDV behavior remains covered as an extension package.
- Trading decisions from extensions still pass through `RiskManager` and `OrderExecutor`.
- Extension command requests are audited and scheduled by the framework.
- Hook timeout and hook exception behavior are covered for P0 and non-critical paths.
- Slow database/history reads, queue backlog, and reconcile delay tests remain outside the P0 trading path.

## Implementation Order

1. Create `extension_api` and migrate public contract types from the legacy strategy SDK package.
2. Convert current `StrategyModule` protocol into broader `ExtensionHooks` plus manifest/factory.
3. Move current business allocation and any remaining business policy into `strategies/current`.
4. Rename generic market parsing so it no longer reads as strategy classification.
5. Wire extension loading through explicit framework configuration.
6. Add command execution pipeline for non-trading side effects.
7. Add hook timeout, error handling, audit, and admin visibility.
8. Remove old names and old imports after call sites are migrated.

## Acceptance Criteria

- `polymarket_trader` framework code contains no FDV, current-strategy, primary outcome, or strategy-threshold
  business semantics.
- Business behavior in the existing bot is implemented under `src/strategies/current/`.
- Extensions can read broad framework state through ports and snapshots.
- Extensions can intervene through documented hooks.
- Extensions request side effects through decisions or commands; they cannot directly bypass risk, order
  execution, persistence, or runtime write controls.
- Full regression and lint pass after migration.
