# Extension API Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the project from a current-strategy bot into a secondary-development framework with a broad Extension API, controlled side effects, and current FDV logic isolated under `src/strategies/current/`.

**Architecture:** Introduce `polymarket_trader.extension_api` as the public contract for business extensions, then migrate framework code away from the legacy strategy SDK package and current-strategy assumptions. Keep framework writes and side effects behind existing app/runtime/infra gates while giving extensions broad read ports, lifecycle hooks, and command request models.

**Tech Stack:** Python 3.12, dataclasses, Protocol types, Pydantic settings, pytest, ruff, existing Polymarket runtime/app/infra layers.

---

## Test Migration Rule

If an existing test only preserves the old single-strategy architecture, old package names, or old public API
surface, delete it or rewrite it as a new extension-boundary test. Do not add compatibility exports, aliases,
or framework code only to satisfy obsolete tests.

Keep tests that protect real framework guarantees: risk gating, order execution path, reconcile behavior,
runtime state, external payload parsing, database persistence, concurrency, and current strategy behavior as
an extension.

---

## File Structure Map

- Create `src/polymarket_trader/extension_api/`: public extension contracts, contexts, decisions, hooks, commands, ports, config loading, and errors.
- Modify `src/strategies/current/`: import the new API, implement current FDV behavior as a business extension, and move equal-weight allocation policy here.
- Modify `src/polymarket_trader/app/strategy_host/`: rename loader concepts from strategy to extension while keeping the directory until call sites are migrated.
- Modify `src/polymarket_trader/app/market_service.py`, `strategy_service.py`, `reconcile_service.py`, and workers: call extension hooks instead of fixed strategy-specific protocols.
- Modify `src/polymarket_trader/config.py` and docs: replace old runtime module naming with `extension_module` and make runtime wiring explicit.
- Rename generic market payload parsing from `domain/classifier.py` into app/infra naming so domain no longer owns external payload parsing.
- Split allocation policy: generic allocation DTOs remain framework-owned, equal-weight allocation moves into the current extension.
- Delete the legacy strategy SDK package after imports and tests migrate.

---

### Task 1: Create Extension API Package

**Files:**
- Create: `src/polymarket_trader/extension_api/__init__.py`
- Create: `src/polymarket_trader/extension_api/config_loader.py`
- Create: `src/polymarket_trader/extension_api/context.py`
- Create: `src/polymarket_trader/extension_api/decisions.py`
- Create: `src/polymarket_trader/extension_api/errors.py`
- Create: `src/polymarket_trader/extension_api/events.py`
- Create: `src/polymarket_trader/extension_api/hooks.py`
- Create: `src/polymarket_trader/extension_api/manifest.py`
- Create: `src/polymarket_trader/extension_api/ports.py`
- Create: `src/polymarket_trader/extension_api/commands.py`
- Test: `tests/extension_api/test_public_contract.py`

- [ ] **Step 1: Write public contract import test**

Create `tests/extension_api/test_public_contract.py`:

```python
from __future__ import annotations

from decimal import Decimal

from polymarket_trader.extension_api import (
    AccountSnapshotView,
    DiscoveryEndpoint,
    DiscoveryQuery,
    EntrySizing,
    ExtensionCommand,
    ExtensionHooks,
    ExtensionManifest,
    FrameworkCommandAction,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyPorts,
    UniverseDecision,
)


def test_extension_api_exports_core_contracts() -> None:
    query = DiscoveryQuery(endpoint=DiscoveryEndpoint.MARKETS, params={"active": True})
    decision = StrategyDecision.buy(
        reason="entry",
        token_id="token",
        price=Decimal("0.42"),
        amount_usdc=Decimal("5"),
    )
    command = ExtensionCommand.pause_market(condition_id="condition", reason="business_pause")

    assert query.endpoint is DiscoveryEndpoint.MARKETS
    assert decision.action is StrategyAction.BUY
    assert command.action is FrameworkCommandAction.PAUSE_MARKET
    assert ExtensionHooks is not None
    assert ExtensionManifest is not None
    assert StrategyContext is not None
    assert StrategyPorts is not None
    assert AccountSnapshotView is not None
    assert EntrySizing is not None
    assert UniverseDecision.include(reason="ok").selected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/extension_api/test_public_contract.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_trader.extension_api'`.

- [ ] **Step 3: Move config loader and error models**

Create `src/polymarket_trader/extension_api/errors.py`:

```python
from __future__ import annotations


class ExtensionLoadError(RuntimeError):
    """Raised when a business extension cannot be loaded or validated."""
```

Create `src/polymarket_trader/extension_api/config_loader.py` by moving the current legacy SDK config loader
implementation and replacing `StrategyLoadError` with `ExtensionLoadError`:

```python
from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
from pathlib import Path
import tomllib
from typing import Any, TypeVar

from polymarket_trader.extension_api.errors import ExtensionLoadError

T = TypeVar("T")


def load_mapping_file(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise ExtensionLoadError(f"extension file not found: {path}")
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix == ".toml":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        raise ExtensionLoadError(
            f"unsupported extension file format '{path.suffix or '<none>'}', expected .json or .toml"
        )
    if not isinstance(data, dict):
        raise ExtensionLoadError(f"extension file must contain an object at top level: {path}")
    return data


def load_extension_config(config_type: type[T], config_path: str | None) -> T | None:
    if config_path is None:
        return None
    if not is_dataclass(config_type):
        raise ExtensionLoadError(f"extension config type must be a dataclass: {config_type!r}")
    data = load_mapping_file(config_path)
    allowed = {field.name for field in fields(config_type)}
    values = {key: value for key, value in data.items() if key in allowed}
    return config_type(**values)
```

- [ ] **Step 4: Create decision and context models**

Move the dataclasses and enums from the legacy SDK models module into:

- `src/polymarket_trader/extension_api/decisions.py`: `StrategyAction`, `DiscoveryEndpoint`,
  `DiscoveryQuery`, `UniverseDecision`, `StrategyDecision`, `EntrySizing`, `RecoveryDecision`,
  `MarketTokenView`, `EntryCandidate`.
- `src/polymarket_trader/extension_api/context.py`: `AccountSnapshotView`, `StrategyContext`.

Keep the existing field names and classmethod constructors so current call sites remain mechanically
migratable.

- [ ] **Step 5: Create broad read ports**

Create `src/polymarket_trader/extension_api/ports.py` by moving and broadening the current port protocols:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from polymarket_trader.domain.events import AuditEvent, Fill
from polymarket_trader.domain.market import Market
from polymarket_trader.domain.order import Order
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.extension_api.context import AccountSnapshotView


class MarketReadPort(Protocol):
    def get_market(
        self,
        *,
        condition_id: str | None = None,
        token_id: str | None = None,
        market_slug: str | None = None,
    ) -> Market | None: ...

    def list_markets(self) -> tuple[Market, ...]: ...


class OrderbookReadPort(Protocol):
    def get_orderbook(self, token_id: str) -> OrderbookSnapshot | None: ...


class AccountReadPort(Protocol):
    def snapshot(self) -> AccountSnapshotView: ...


class HistoryReadPort(Protocol):
    def open_orders(self, *, condition_id: str, token_id: str) -> tuple[Order, ...]: ...
    def recent_fills(self, *, condition_id: str | None = None, limit: int = 100) -> tuple[Fill, ...]: ...
    def recent_audit_events(self, *, condition_id: str | None = None, limit: int = 100) -> tuple[AuditEvent, ...]: ...


class RuntimeReadPort(Protocol):
    def is_market_paused(self, condition_id: str) -> bool: ...
    def can_open_new_entries(self) -> bool: ...


class ConfigReadPort(Protocol):
    def sanitized_framework_config(self) -> Mapping[str, Any]: ...
    def extension_config_metadata(self) -> Mapping[str, Any]: ...


class TelemetryPort(Protocol):
    def record_event(self, name: str, *, attributes: Mapping[str, Any] | None = None) -> None: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class StrategyPorts:
    market: MarketReadPort | None = None
    orderbook: OrderbookReadPort | None = None
    account: AccountReadPort | None = None
    history: HistoryReadPort | None = None
    runtime: RuntimeReadPort | None = None
    config: ConfigReadPort | None = None
    telemetry: TelemetryPort | None = None
    clock: ClockPort | None = None
```

- [ ] **Step 6: Create command models**

Create `src/polymarket_trader/extension_api/commands.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class FrameworkCommandAction(StrEnum):
    PAUSE_MARKET = "pause_market"
    RESUME_MARKET = "resume_market"
    PAUSE_ENTRIES = "pause_entries"
    TRIGGER_RECONCILE = "trigger_reconcile"
    REFRESH_MARKET = "refresh_market"
    EMIT_ALERT = "emit_alert"
    RECORD_AUDIT = "record_audit"
    SUBSCRIBE_MARKET = "subscribe_market"
    UNSUBSCRIBE_MARKET = "unsubscribe_market"


@dataclass(frozen=True, slots=True)
class ExtensionCommand:
    action: FrameworkCommandAction
    reason: str
    condition_id: str | None = None
    token_id: str | None = None
    market_slug: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def pause_market(cls, *, condition_id: str, reason: str) -> "ExtensionCommand":
        return cls(action=FrameworkCommandAction.PAUSE_MARKET, condition_id=condition_id, reason=reason)

    @classmethod
    def trigger_reconcile(cls, *, reason: str, condition_id: str | None = None) -> "ExtensionCommand":
        return cls(action=FrameworkCommandAction.TRIGGER_RECONCILE, condition_id=condition_id, reason=reason)
```

- [ ] **Step 7: Create hooks and manifest protocols**

Create `src/polymarket_trader/extension_api/hooks.py` with the current required methods plus command-aware
optional hooks:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from polymarket_trader.domain.market import Market
from polymarket_trader.extension_api.commands import ExtensionCommand
from polymarket_trader.extension_api.context import AccountSnapshotView, StrategyContext
from polymarket_trader.extension_api.decisions import (
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategyDecision,
    UniverseDecision,
)


@dataclass(frozen=True, slots=True)
class HookResult:
    commands: tuple[ExtensionCommand, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class ExtensionHooks(Protocol):
    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]: ...
    def select_market(self, market: Market) -> UniverseDecision: ...
    def size_entry(self, context: StrategyContext) -> EntrySizing: ...
    def decide_entry(self, context: StrategyContext) -> StrategyDecision: ...
    def decide_exit(self, context: StrategyContext) -> StrategyDecision: ...
    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision: ...
    def decide_follow_up(self, context: StrategyContext) -> tuple[StrategyDecision, ...]: ...
    def should_keep_tracking(self, market: Market, account_snapshot: AccountSnapshotView | None) -> bool: ...
    def build_filtered_tracking_market(self, candidate_market: Market, *, existing_market: Market, reason: str) -> Market: ...
```

Create `src/polymarket_trader/extension_api/manifest.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from polymarket_trader.extension_api.hooks import ExtensionHooks
from polymarket_trader.extension_api.ports import StrategyPorts


@dataclass(frozen=True, slots=True)
class ExtensionSpec:
    name: str
    version: str = "1"
    description: str = ""
    config_type: type[Any] | None = None
    capabilities: tuple[str, ...] = ()


@runtime_checkable
class BusinessExtension(Protocol):
    @property
    def spec(self) -> ExtensionSpec: ...
    @property
    def hooks(self) -> ExtensionHooks: ...


class ExtensionFactory(Protocol):
    def __call__(
        self,
        *,
        ports: StrategyPorts | None = None,
        config_path: str | None = None,
    ) -> BusinessExtension: ...


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    module_path: str
    factory: ExtensionFactory
```

- [ ] **Step 8: Export public API**

Create `src/polymarket_trader/extension_api/__init__.py` that re-exports all public classes from the package.
Include aliases only for concepts still intentionally named strategy, such as `StrategyDecision` and
`StrategyContext`, because they describe trading strategy decisions rather than the package name.

- [ ] **Step 9: Run focused test**

Run: `pytest tests/extension_api/test_public_contract.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/polymarket_trader/extension_api tests/extension_api/test_public_contract.py
git commit -m "feat: add extension API contracts"
```

---

### Task 2: Migrate Public Imports From The Legacy SDK To `extension_api`

**Files:**
- Modify: all Python files currently importing the legacy SDK
- Modify the legacy SDK config loader test and move it to `tests/extension_api/test_config_loader.py`
- Delete the legacy SDK package
- Delete the legacy SDK tests

- [ ] **Step 1: Write import-boundary test**

Create `tests/extension_api/test_no_legacy_sdk_imports.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_runtime_no_longer_imports_legacy_sdk() -> None:
    roots = [Path("src/polymarket_trader"), Path("src/strategies"), Path("tests")]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "legacy_sdk_package_marker" in text:
                offenders.append(str(path))
    assert offenders == []
```

- [ ] **Step 2: Run boundary test to verify it fails**

Run: `pytest tests/extension_api/test_no_legacy_sdk_imports.py -q`

Expected: FAIL with offenders including `src/strategies/current/strategy.py` and framework services.

- [ ] **Step 3: Replace imports mechanically**

Run a mechanical import rewrite from the legacy SDK package to `polymarket_trader.extension_api`.

Then inspect for legacy SDK imports under `src` and `tests`.

Expected: only deleted legacy SDK files still match before removal.

- [ ] **Step 4: Move config loader tests**

Move the legacy SDK config loader test to `tests/extension_api/test_config_loader.py`.
Update imports to:

```python
from polymarket_trader.extension_api import (
    load_extension_config as exported_load_extension_config,
)
from polymarket_trader.extension_api.config_loader import load_mapping_file, load_extension_config
from polymarket_trader.extension_api.errors import ExtensionLoadError
```

Update assertions so they reference `load_extension_config`.

- [ ] **Step 5: Delete old SDK package**

Run:

```bash
git rm -r <legacy-sdk-package> <legacy-sdk-tests>
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/extension_api -q
```

Expected: PASS.

- [ ] **Step 7: Run lint and full tests**

Run:

```bash
ruff check .
pytest -q
```

Expected: `ruff` passes; pytest reports all existing tests passing with the same skipped count as baseline unless intentional renamed tests change the count.

- [ ] **Step 8: Commit**

Run:

```bash
git add src tests
git commit -m "refactor: migrate strategy SDK to extension API"
```

---

### Task 3: Rename Runtime Loading From Strategy to Extension

**Files:**
- Modify: `src/polymarket_trader/config.py`
- Modify: `src/polymarket_trader/main.py`
- Modify: `src/polymarket_trader/app/strategy_host/loader.py`
- Modify: `src/polymarket_trader/app/strategy_host/__init__.py`
- Modify: `src/polymarket_trader/app/strategy_host/replay.py`
- Modify: docs and tests referencing old runtime module configuration

- [ ] **Step 1: Write settings test**

Create `tests/app/test_extension_config.py`:

```python
from __future__ import annotations

from polymarket_trader.config import Settings


def test_settings_use_extension_module_naming() -> None:
    settings = Settings(extension_module="strategies.current")

    assert settings.extension_module == "strategies.current"
    assert settings.sanitized_dump()["extension_module"] == "strategies.current"
```

- [ ] **Step 2: Run settings test to verify it fails**

Run: `pytest tests/app/test_extension_config.py -q`

Expected: FAIL because `Settings` does not define `extension_module`.

- [ ] **Step 3: Rename settings fields**

In `src/polymarket_trader/config.py`, replace:

```python
legacy module/config fields
```

with:

```python
extension_module: str | None = None
extension_config_path: str | None = None
```

Update `_blank_string_to_none` to include `extension_module` and `extension_config_path`.
Update `sanitized_dump()` consumers and docs to use the new names.

- [ ] **Step 4: Add readiness issue for missing extension module**

In `Settings.validate_startup_readiness()`, append a blocking issue when `extension_module` is missing:

```python
if self.extension_module is None or not self.extension_module.strip():
    blocking_issues.append(
        ConfigIssue(
            field="extension_module",
            code="missing_extension_module",
            message="必须显式配置二次开发业务扩展模块。",
        )
    )
```

- [ ] **Step 5: Rename loader functions**

In `src/polymarket_trader/app/strategy_host/loader.py`, rename public functions:

```python
def load_extension(...)
def load_extension_manifest(...)
```

Use `ExtensionLoadError`, `ExtensionManifest`, `BusinessExtension`, and `StrategyPorts` from
`polymarket_trader.extension_api`.

The validation error should say:

```python
f"extension factory '{manifest.module_path}' did not return a BusinessExtension-compatible object"
```

- [ ] **Step 6: Update main runtime wiring**

In `src/polymarket_trader/main.py`, rename fields in `RuntimeComponents`:

```python
extension: BusinessExtension
```

Load with:

```python
if settings.extension_module is None:
    raise ConfigLoadError(
        [
            ConfigIssue(
                field="extension_module",
                code="missing_extension_module",
                message="必须显式配置二次开发业务扩展模块。",
            )
        ]
    )
extension = load_extension(
    module_path=settings.extension_module,
    ports=strategy_ports,
    config_path=settings.extension_config_path,
)
```

Pass `extension.hooks` to services that only need hooks.

- [ ] **Step 7: Update replay default**

In `src/polymarket_trader/app/strategy_host/replay.py`, rename parameters to `extension_module` and
`extension_config_path`. Keep the replay helper default as `"strategies.current"` because replay is a
developer example entry point, not framework startup policy.

- [ ] **Step 8: Update tests with explicit extension config**

Every test that calls `Settings()` and then `build_runtime()` must pass:

```python
Settings(extension_module="strategies.current")
```

Tests that construct fake services directly can keep passing fake hook objects.

- [ ] **Step 9: Run focused tests**

Run:

```bash
pytest tests/app/test_extension_config.py tests/app/test_runtime.py -q
```

Expected: PASS.

- [ ] **Step 10: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests docs
git commit -m "refactor: rename strategy loading to extension loading"
```

---

### Task 4: Rename Generic Market Parsing Out of Domain Classifier

**Files:**
- Create: `src/polymarket_trader/app/market_payload_parser.py`
- Modify: `src/polymarket_trader/app/market_service.py`
- Move: `tests/domain/test_classifier.py` -> `tests/app/test_market_payload_parser.py`
- Delete: `src/polymarket_trader/domain/classifier.py`

- [ ] **Step 1: Write domain-boundary test**

Create `tests/domain/test_domain_import_boundaries.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_domain_does_not_own_external_market_payload_parser() -> None:
    domain_files = [path.name for path in Path("src/polymarket_trader/domain").glob("*.py")]
    assert "classifier.py" not in domain_files
```

- [ ] **Step 2: Run boundary test to verify it fails**

Run: `pytest tests/domain/test_domain_import_boundaries.py -q`

Expected: FAIL because `classifier.py` exists.

- [ ] **Step 3: Move parser code**

Move `src/polymarket_trader/domain/classifier.py` to
`src/polymarket_trader/app/market_payload_parser.py`.

Rename:

- `ClassificationStatus` -> `MarketParseStatus`
- `ClassificationRejectReason` -> `MarketParseRejectReason`
- `ClassificationResult` -> `MarketParseResult`
- `MarketClassifier` -> `MarketPayloadParser`
- `classify()` -> `parse()`

Keep methods such as `to_market()` and payload parsing behavior unchanged.

- [ ] **Step 4: Update market service**

In `src/polymarket_trader/app/market_service.py`, change constructor dependencies:

```python
from polymarket_trader.app.market_payload_parser import MarketParseResult, MarketPayloadParser

parser: MarketPayloadParser | None = None
self._parser = parser or MarketPayloadParser()
parse_result = self._parser.parse(raw_market)
```

Rename `classification` local variables to `parse_result` in this file.
Payload fields should become `parse_status`, `parse_reason`, and `parse_detail`.

- [ ] **Step 5: Move tests and update names**

Move `tests/domain/test_classifier.py` to `tests/app/test_market_payload_parser.py`.
Update imports and assertions to use the new class names.

- [ ] **Step 6: Delete old domain parser**

Run:

```bash
git rm src/polymarket_trader/domain/classifier.py
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/app/test_market_payload_parser.py tests/app/test_market_service.py tests/domain/test_domain_import_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 8: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests
git commit -m "refactor: move market payload parsing out of domain"
```

---

### Task 5: Move Equal-Weight Allocation Policy Into Current Extension

**Files:**
- Create: `src/strategies/current/allocation.py`
- Modify: `src/polymarket_trader/domain/allocation.py`
- Modify: `src/strategies/current/trading.py`
- Move: `tests/domain/test_allocation.py` policy tests into `tests/strategies/current/test_allocation.py`
- Add: generic allocation DTO tests under `tests/domain/test_allocation_contract.py`

- [ ] **Step 1: Write framework-neutral allocation test**

Create `tests/domain/test_allocation_contract.py`:

```python
from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.allocation import Allocation, AllocationPlan


def test_allocation_plan_is_data_contract_without_policy_constructor() -> None:
    plan = AllocationPlan(
        trace_id="trace",
        total_budget_usdc=Decimal("10"),
        allocations=(
            Allocation(
                condition_id="condition",
                token_id="token",
                target_budget_usdc=Decimal("10"),
                buy_budget_usdc=Decimal("5"),
            ),
        ),
    )

    assert plan.allocated_budget_usdc == Decimal("5")
    assert not hasattr(AllocationPlan, "equal_weight")
```

- [ ] **Step 2: Run contract test to verify it fails**

Run: `pytest tests/domain/test_allocation_contract.py -q`

Expected: FAIL because `AllocationPlan.equal_weight` still exists.

- [ ] **Step 3: Create current allocation policy module**

Create `src/strategies/current/allocation.py` by moving these from `domain/allocation.py`:

- `AllocationMarketSnapshot`
- `equal_weight_budget`
- equal-weight planning function currently implemented as `AllocationPlan.equal_weight`
- helper functions used only by equal-weight allocation, including market liquidity and capacity helpers

Expose a top-level function:

```python
def equal_weight_plan(
    *,
    trace_id: str,
    portfolio_budget_usdc: Decimal,
    markets: Iterable[AllocationMarketSnapshot],
    available_usdc: Decimal,
    max_order_usdc: Decimal,
    max_market_usdc: Decimal,
    max_total_usdc: Decimal,
) -> AllocationPlan:
    ...
```

- [ ] **Step 4: Keep generic allocation DTOs in domain**

In `src/polymarket_trader/domain/allocation.py`, keep only:

- `Allocation`
- `MarketBuyBudgetChanged`
- `AllocationPlan`
- `current_exposure_usdc`

Remove `AllocationPlan.equal_weight` and policy-only helper functions.

- [ ] **Step 5: Update current trading code**

In `src/strategies/current/trading.py`, replace imports:

```python
from polymarket_trader.domain.allocation import Allocation, AllocationPlan, current_exposure_usdc
from strategies.current.allocation import AllocationMarketSnapshot, equal_weight_plan
```

Replace:

```python
eligible_plan = AllocationPlan.equal_weight(...)
```

with:

```python
eligible_plan = equal_weight_plan(...)
```

- [ ] **Step 6: Move policy tests**

Move equal-weight tests from `tests/domain/test_allocation.py` to
`tests/strategies/current/test_allocation.py`.
Update imports to:

```python
from strategies.current.allocation import AllocationMarketSnapshot, equal_weight_budget, equal_weight_plan
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/domain/test_allocation_contract.py tests/strategies/current/test_allocation.py tests/strategies/current/test_current_strategy.py -q
```

Expected: PASS.

- [ ] **Step 8: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests
git commit -m "refactor: move allocation policy into current extension"
```

---

### Task 6: Add Controlled Extension Command Execution

**Files:**
- Create: `src/polymarket_trader/app/extension_commands.py`
- Create: `tests/app/test_extension_commands.py`
- Modify: `src/polymarket_trader/runtime/account_state.py`
- Modify: `src/polymarket_trader/runtime/registry.py`

- [ ] **Step 1: Write command executor tests**

Create `tests/app/test_extension_commands.py`:

```python
from __future__ import annotations

from polymarket_trader.app.extension_commands import ExtensionCommandExecutor
from polymarket_trader.extension_api import ExtensionCommand, FrameworkCommandAction
from polymarket_trader.runtime.account_state import AccountStateStore


def test_pause_market_command_updates_runtime_state() -> None:
    account_state = AccountStateStore()
    executor = ExtensionCommandExecutor(account_state_store=account_state)

    result = executor.execute(
        ExtensionCommand.pause_market(condition_id="condition", reason="business_pause"),
        trace_id="trace",
    )

    snapshot = account_state.snapshot()
    assert result.accepted
    assert result.action is FrameworkCommandAction.PAUSE_MARKET
    assert snapshot.is_market_paused("condition")


def test_trigger_reconcile_command_is_recorded_without_direct_side_effect() -> None:
    executor = ExtensionCommandExecutor()
    result = executor.execute(
        ExtensionCommand.trigger_reconcile(condition_id="condition", reason="manual_recheck"),
        trace_id="trace",
    )

    assert result.accepted
    assert result.action is FrameworkCommandAction.TRIGGER_RECONCILE
    assert result.command.reason == "manual_recheck"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/app/test_extension_commands.py -q`

Expected: FAIL because `ExtensionCommandExecutor` does not exist.

- [ ] **Step 3: Implement command result and executor**

Create `src/polymarket_trader/app/extension_commands.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from polymarket_trader.extension_api import ExtensionCommand, FrameworkCommandAction
from polymarket_trader.runtime.account_state import AccountStateStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ExtensionCommandResult:
    command: ExtensionCommand
    action: FrameworkCommandAction
    accepted: bool
    trace_id: str
    reason: str
    executed_at: datetime


class ExtensionCommandExecutor:
    def __init__(self, *, account_state_store: AccountStateStore | None = None) -> None:
        self._account_state_store = account_state_store

    def execute(self, command: ExtensionCommand, *, trace_id: str) -> ExtensionCommandResult:
        accepted = True
        if command.action is FrameworkCommandAction.PAUSE_MARKET and command.condition_id:
            if self._account_state_store is not None:
                self._account_state_store.pause_market(command.condition_id)
        elif command.action is FrameworkCommandAction.RESUME_MARKET and command.condition_id:
            if self._account_state_store is not None:
                self._account_state_store.resume_market(command.condition_id)
        return ExtensionCommandResult(
            command=command,
            action=command.action,
            accepted=accepted,
            trace_id=trace_id,
            reason=command.reason,
            executed_at=_utc_now(),
        )
```

- [ ] **Step 4: Add runtime methods if missing**

If `AccountStateStore` does not expose `pause_market()` and `resume_market()`, add:

```python
def pause_market(self, condition_id: str) -> None:
    with self._lock:
        self._paused_markets.add(condition_id)


def resume_market(self, condition_id: str) -> None:
    with self._lock:
        self._paused_markets.discard(condition_id)
```

Use the existing lock and internal paused-market storage names from `account_state.py`.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/app/test_extension_commands.py -q`

Expected: PASS.

- [ ] **Step 6: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests
git commit -m "feat: add controlled extension commands"
```

---

### Task 7: Wire Extension Hooks Through App Services

**Files:**
- Modify: `src/polymarket_trader/app/market_service.py`
- Modify: `src/polymarket_trader/app/strategy_service.py`
- Modify: `src/polymarket_trader/app/reconcile_service.py`
- Modify: `src/polymarket_trader/workers/strategy_worker.py`
- Modify: `src/strategies/current/strategy.py`
- Test: existing app and current strategy tests

- [ ] **Step 1: Write service constructor test**

Add to `tests/app/test_strategy_service.py`:

```python
def test_strategy_service_accepts_extension_hooks_name() -> None:
    hooks = _CustomSizingStrategy()
    service = StrategyService(extension_hooks=hooks)

    assert service is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/app/test_strategy_service.py::test_strategy_service_accepts_extension_hooks_name -q`

Expected: FAIL because `StrategyService` still expects the old constructor keyword.

- [ ] **Step 3: Rename service constructor dependencies**

Update constructors:

```python
def __init__(self, *, extension_hooks: ExtensionHooks, ...)
```

Store as:

```python
self._extension_hooks = extension_hooks
```

Replace calls like:

```python
self._extension_hooks.decide_entry(...)
```

with:

```python
self._extension_hooks.decide_entry(...)
```

Apply this to market, strategy, and reconcile services.

- [ ] **Step 4: Update current extension object**

In `src/strategies/current/strategy.py`, implement:

```python
@property
def hooks(self) -> ExtensionHooks:
    return self
```

Keep existing business methods on `CurrentStrategy` so it satisfies `ExtensionHooks`.

- [ ] **Step 5: Update runtime wiring**

In `main.py`, pass:

```python
extension_hooks=extension.hooks
```

to `MarketService`, `StrategyService`, and `ReconcileService`.

- [ ] **Step 6: Update fake strategies in tests**

Rename service-construction tests to use `extension_hooks=` when constructing services directly.
Fake classes can keep their method names because they implement the hook protocol.

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/app/test_market_service.py tests/app/test_strategy_service.py tests/app/test_reconcile_worker.py -q
```

Expected: PASS.

- [ ] **Step 8: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests
git commit -m "refactor: wire app services through extension hooks"
```

---

### Task 8: Remove Current-Business Residue From Framework

**Files:**
- Modify: `src/polymarket_trader/**/*.py`
- Modify: `docs/*.md`
- Modify: `tests/**/*.py`

- [ ] **Step 1: Write residue scan test**

Create `tests/app/test_framework_business_boundaries.py`:

```python
from __future__ import annotations

from pathlib import Path


FORBIDDEN_FRAMEWORK_TERMS = (
    "strategies.current",
    "CurrentStrategy",
    "FDV",
    "fully diluted valuation",
    "entry_no_price",
    "exit_no_price",
    "primary outcome",
)


def test_framework_code_does_not_reference_current_business_terms() -> None:
    offenders: dict[str, list[str]] = {}
    for path in Path("src/polymarket_trader").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = [term for term in FORBIDDEN_FRAMEWORK_TERMS if term in text]
        if hits:
            offenders[str(path)] = hits
    assert offenders == {}
```

- [ ] **Step 2: Run scan test**

Run: `pytest tests/app/test_framework_business_boundaries.py -q`

Expected: PASS after previous tasks. If it fails, each offender is a concrete cleanup target.

- [ ] **Step 3: Clean framework strings**

For each offender, replace current-business naming with extension-neutral naming. Examples:

- old module keyword -> `extension_hooks` or `extension_module`
- old selected payload key -> `extension_selected`
- old reason payload key -> `extension_reason`
- old factory error text -> `extension factory`

- [ ] **Step 4: Update docs**

Update `docs/设计文档.md`, `docs/config.md`, `docs/api.md`, and strategy README files so they describe:

```text
extension_module
extension_config_path
polymarket_trader.extension_api
strategies/current as the example/current business extension
```

- [ ] **Step 5: Run full verification and commit**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

Commit:

```bash
git add src tests docs
git commit -m "chore: remove current business residue from framework"
```

---

### Task 9: Final Verification and Integration Notes

**Files:**
- Modify: `docs/superpowers/specs/2026-04-22-extension-api-refactor-design.md` only if implementation reveals a necessary clarification.

- [ ] **Step 1: Run acceptance scans**

Run:

```bash
rg -n "<legacy-sdk-import-marker>" src tests docs
rg -n "strategies\\.current|CurrentStrategy|FDV|fully diluted valuation|entry_no_price|exit_no_price" src/polymarket_trader tests/app tests/domain
```

Expected:

- First command returns no results.
- Second command returns no framework/app/domain test offenders. Matches under `src/strategies/current`,
  `tests/strategies/current`, or docs that explicitly describe the example extension are acceptable.

- [ ] **Step 2: Run full regression**

Run:

```bash
ruff check .
pytest -q
```

Expected: all checks pass.

- [ ] **Step 3: Inspect git history**

Run:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Expected: worktree is clean on `extension-api-refactor`; recent commits correspond to the tasks above.

- [ ] **Step 4: Commit spec clarification if needed**

If the implementation required a design clarification, edit the spec and commit:

```bash
git add docs/superpowers/specs/2026-04-22-extension-api-refactor-design.md
git commit -m "docs: clarify extension API implementation details"
```

If no clarification is needed, leave the spec unchanged.
