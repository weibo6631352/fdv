from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from polymarket_trader.app.admin_serialization import AdminSerializer, decimal_text, jsonable
from polymarket_trader.domain.account import AccountSnapshot
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.runtime.event_bus import QueueDepthSnapshot
from polymarket_trader.runtime.registry import MarketRegistrySnapshot
from polymarket_trader.serialization import utc_now


@dataclass(frozen=True, slots=True)
class AdminRuntimeView:
    runtime: Any | None = None

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "timestamp": utc_now().isoformat(),
        }

    def readiness_snapshot(self) -> dict[str, Any]:
        config_readiness = self._config_readiness_snapshot()
        runtime_snapshot = self._runtime_status_snapshot()
        blocking_issues = self._runtime_blocking_issues(config_readiness, runtime_snapshot)
        ready_to_trade = bool(runtime_snapshot.get("ready_to_trade")) and not blocking_issues
        return {
            "ready_to_trade": ready_to_trade,
            "phase": runtime_snapshot["phase"],
            "blocking_issues": blocking_issues,
            "warnings": list(config_readiness.get("warnings", [])),
            "runtime": runtime_snapshot,
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        runtime_status = self._runtime_status_snapshot()
        account = self._account_snapshot()
        registry = self._registry_snapshot()
        market_discovery = self._market_discovery_snapshot()
        event_bus = self._event_bus_snapshot()
        persistence = self._persistence_snapshot()
        markets = [self._serializer().market_view(market) for market in registry.markets]
        return {
            "phase": runtime_status["phase"],
            "ready_to_trade": runtime_status["ready_to_trade"],
            "readiness": self._readiness_summary(),
            "settings": self._settings_snapshot(),
            "identity": self._identity_snapshot(),
            "runtime": runtime_status,
            "bootstrap_summary": jsonable(getattr(self.runtime, "bootstrap_summary", {})),
            "market_discovery": market_discovery,
            "registry": {
                "market_count": len(registry.markets),
                "markets": [jsonable(market) for market in markets],
            },
            "account": self._serializer().account_snapshot(account),
            "event_bus": jsonable(event_bus) if event_bus is not None else None,
            "persistence": jsonable(persistence) if persistence is not None else None,
            "markets": markets,
            "portfolio": self._serializer().portfolio_snapshot(account),
        }

    def workers_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            return {
                "phase": payload.get("phase", "starting"),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "status_reason": payload.get("status_reason"),
                "queue_depths": payload.get("queue_depths"),
                "scheduler": payload.get("scheduler"),
                "workers": list(payload.get("worker_health", ())),
            }

        runtime_status = self._runtime_status_snapshot()
        return {
            "phase": runtime_status["phase"],
            "automatic_trading_enabled": bool(runtime_status.get("automatic_trading_enabled")),
            "status_reason": None,
            "queue_depths": runtime_status.get("queue_depth"),
            "scheduler": None,
            "workers": [],
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            return {
                "phase": payload.get("phase", "starting"),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "status_reason": payload.get("status_reason"),
                "queue_depths": payload.get("queue_depths"),
                "metrics": payload.get("metrics"),
            }

        metrics = getattr(self.runtime, "metrics", None)
        metrics_payload = None
        if metrics is not None and hasattr(metrics, "snapshot"):
            snapshot = metrics.snapshot()
            metrics_payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
        runtime_status = self._runtime_status_snapshot()
        return {
            "phase": runtime_status["phase"],
            "automatic_trading_enabled": bool(runtime_status.get("automatic_trading_enabled")),
            "status_reason": None,
            "queue_depths": runtime_status.get("queue_depth"),
            "metrics": metrics_payload,
        }

    def _runtime_status_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            readiness = payload.get("readiness") or {}
            user_ws = payload.get("user_ws") or {}
            account = payload.get("account") or {}
            return {
                "phase": payload.get("phase", "starting"),
                "ready_to_trade": bool(readiness.get("ready")),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "user_ws_connected": bool(user_ws.get("connected", account.get("user_ws_connected", False))),
                "allow_new_entries": bool(account.get("allow_new_entries", False)),
                "last_reconcile_at": readiness.get("last_reconcile_at") or account.get("last_reconcile_at"),
                "portfolio_budget_usdc": decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
                "queue_depth": payload.get("queue_depths"),
                "persistence": payload.get("persistence"),
                "blocking_reasons": tuple(readiness.get("blocking_reasons", ())),
                "warnings": tuple(readiness.get("warnings", ())),
            }

        readiness = self._config_readiness_snapshot()
        account = self._account_snapshot()
        persistence = self._persistence_snapshot()
        event_bus = self._event_bus_snapshot()
        raw_low_priority_paused = getattr(event_bus, "low_priority_paused", False) if event_bus is not None else False
        low_priority_paused = bool(raw_low_priority_paused() if callable(raw_low_priority_paused) else raw_low_priority_paused)
        phase = "starting"
        ready_to_trade = bool(readiness.get("ready_to_trade"))
        if account.last_reconcile_at is None:
            phase = "recovering_snapshot"
        elif not account.user_ws_connected or not account.allow_new_entries:
            phase = "paused"
        elif persistence is not None and (
            getattr(persistence, "last_error", None) is not None
            or (getattr(persistence, "outbox_depth", 0) > 0 and low_priority_paused)
        ):
            phase = "degraded"
        elif ready_to_trade:
            phase = "trading_enabled"
        return {
            "phase": phase,
            "ready_to_trade": ready_to_trade and account.user_ws_connected and account.allow_new_entries,
            "user_ws_connected": account.user_ws_connected,
            "allow_new_entries": account.allow_new_entries,
            "last_reconcile_at": jsonable(account.last_reconcile_at),
            "portfolio_budget_usdc": decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
            "queue_depth": jsonable(event_bus) if event_bus is not None else None,
            "persistence": jsonable(persistence) if persistence is not None else None,
        }

    def _config_readiness_snapshot(self) -> dict[str, Any]:
        settings = getattr(self.runtime, "readiness", None)
        if settings is not None:
            return settings.as_dict()
        return {
            "ready_to_trade": False,
            "blocking_issues": [],
            "warnings": [],
        }

    def _runtime_blocking_issues(
        self,
        config_readiness: dict[str, Any],
        runtime_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blocking_issues = list(config_readiness.get("blocking_issues", []))
        has_config_blockers = bool(blocking_issues)
        runtime_blocking_reason_list = tuple(str(reason) for reason in runtime_snapshot.get("blocking_reasons", ()))
        runtime_blocking_reasons = set(runtime_blocking_reason_list)
        seen_issue_keys = {
            (str(issue.get("field", "")), str(issue.get("code", "")))
            for issue in blocking_issues
            if isinstance(issue, Mapping)
        }

        def append_issue(field: str, code: str, message: str) -> None:
            issue_key = (field, code)
            if issue_key in seen_issue_keys:
                return
            seen_issue_keys.add(issue_key)
            blocking_issues.append(
                {
                    "field": field,
                    "code": code,
                    "message": message,
                }
            )

        for reason in runtime_blocking_reason_list:
            issue = self._runtime_blocking_issue_from_reason(reason, has_config_blockers=has_config_blockers)
            if issue is None:
                continue
            append_issue(str(issue["field"]), str(issue["code"]), str(issue["message"]))

        user_ws_connected = bool(runtime_snapshot.get("user_ws_connected"))
        last_reconcile_at = runtime_snapshot.get("last_reconcile_at")
        allow_new_entries = bool(runtime_snapshot.get("allow_new_entries"))
        has_runtime_client_blocker = {
            "trading_client_not_ready",
            "trading_client_unavailable",
        }.intersection(runtime_blocking_reasons)
        expose_runtime_account_blockers = not has_config_blockers and not has_runtime_client_blocker
        if expose_runtime_account_blockers and not user_ws_connected:
            append_issue(
                "user_ws_connected",
                "ws_disconnected",
                "用户行情连接未连接，暂停自动下单",
            )
        if expose_runtime_account_blockers and last_reconcile_at is None:
            append_issue(
                "last_reconcile_at",
                "reconcile_pending",
                "首次 reconcile 未完成，禁止自动下单",
            )
        if expose_runtime_account_blockers and not allow_new_entries and user_ws_connected and last_reconcile_at is not None:
            append_issue(
                "allow_new_entries",
                "buy_gate_closed",
                "自动买入闸门关闭",
            )
        return blocking_issues

    def _runtime_blocking_issue_from_reason(
        self,
        reason: str,
        *,
        has_config_blockers: bool,
    ) -> dict[str, str] | None:
        if reason in {
            "config_not_ready",
            "user_ws_not_connected",
            "reconcile_not_fresh",
        }:
            return None
        if reason.startswith("phase="):
            return None
        if reason == "db_not_ready" or reason == "database_unavailable":
            return {
                "field": "database",
                "code": "database_unavailable",
                "message": "数据库连接未就绪，暂停自动下单",
            }
        if reason == "market_ws_not_connected":
            return {
                "field": "market_ws_connected",
                "code": "ws_disconnected",
                "message": "市场行情连接未连接，暂停自动下单",
            }
        if reason == "outbox_backlog_high":
            return {
                "field": "outbox_depth",
                "code": "backlog_high",
                "message": "外发队列积压过高，暂停自动下单",
            }
        if reason == "trading_client_not_ready":
            if has_config_blockers:
                return None
            return {
                "field": "trading_client",
                "code": "client_not_ready",
                "message": "交易客户端未就绪，暂停自动下单",
            }
        if reason == "trading_client_unavailable":
            if has_config_blockers:
                return None
            return {
                "field": "trading_client",
                "code": "client_unavailable",
                "message": "交易客户端不可用，暂停自动下单",
            }
        if reason.startswith("startup_reconcile_failed:"):
            detail = reason.split(":", 1)[1].strip()
            message = "启动对账失败，暂停自动下单"
            if detail:
                message = f"{message}：{detail}"
            return {
                "field": "startup_reconcile",
                "code": "startup_reconcile_failed",
                "message": message,
            }
        return None

    def _readiness_summary(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            readiness = snapshot.readiness
            if readiness is not None:
                return readiness.as_dict() if hasattr(readiness, "as_dict") else jsonable(readiness)
        config_readiness = self._config_readiness_snapshot()
        runtime_snapshot = self._runtime_status_snapshot()
        blocking_issues = self._runtime_blocking_issues(config_readiness, runtime_snapshot)
        return {
            "ready_to_trade": bool(config_readiness.get("ready_to_trade")) and not blocking_issues,
            "phase": runtime_snapshot["phase"],
            "blocking_issues": blocking_issues,
            "warnings": list(config_readiness.get("warnings", [])),
        }

    def _settings_snapshot(self) -> dict[str, Any]:
        settings = self._settings()
        if settings is None:
            return {}
        if hasattr(settings, "sanitized_dump"):
            return settings.sanitized_dump()
        return jsonable(settings)

    def _identity_snapshot(self) -> dict[str, Any]:
        settings = self._settings()
        wallet_address = None
        for component_name in ("clob_client", "data_client"):
            component = getattr(self.runtime, component_name, None)
            if component is None:
                continue
            candidate = getattr(component, "default_wallet_address", None)
            if callable(candidate):
                candidate = candidate()
            if candidate:
                wallet_address = str(candidate)
                break
        return {
            "wallet_address": wallet_address,
            "funder_address": (
                getattr(settings, "polymarket_funder_address", None) if settings is not None else None
            ),
            "signature_type": (
                getattr(settings, "polymarket_signature_type", None) if settings is not None else None
            ),
        }

    def _serializer(self) -> AdminSerializer:
        return AdminSerializer(
            account_snapshot_provider=self._account_snapshot,
            registry_snapshot_provider=self._registry_snapshot,
            market_ws_snapshot=self._market_ws_snapshot,
        )

    def _account_snapshot(self) -> AccountSnapshot:
        account_state = getattr(self.runtime, "account_state_store", None)
        if account_state is not None:
            return account_state.snapshot()
        return AccountSnapshot()

    def _registry_snapshot(self) -> MarketRegistrySnapshot:
        registry = getattr(self.runtime, "registry", None)
        if registry is not None:
            return registry.snapshot()
        return MarketRegistrySnapshot(tuple())

    def _event_bus_snapshot(self) -> QueueDepthSnapshot | None:
        event_bus = getattr(self.runtime, "event_bus", None)
        if event_bus is None:
            return None
        return event_bus.snapshot()

    def _persistence_snapshot(self) -> Any | None:
        worker = getattr(self.runtime, "persistence_worker", None)
        if worker is None:
            return None
        return worker.snapshot()

    def _market_discovery_snapshot(self) -> dict[str, Any]:
        state = getattr(self.runtime, "market_discovery_scan", None)
        if state is None:
            return {
                "round_id": 0,
                "cursor_active": False,
                "round_started_at": None,
                "last_round_completed_at": None,
                "pages_scanned_in_round": 0,
                "markets_seen_in_round": 0,
                "last_completed_round_pages": 0,
                "last_completed_round_markets": 0,
                "last_page_size": 0,
                "last_tick_started_at": None,
                "last_tick_completed_at": None,
                "last_tick_requests": 0,
                "last_tick_markets": 0,
                "last_error": None,
                "consecutive_failures": 0,
            }
        return {
            "round_id": int(getattr(state, "round_id", 0)),
            "cursor_active": getattr(state, "after_cursor", None) is not None,
            "round_started_at": jsonable(getattr(state, "round_started_at", None)),
            "last_round_completed_at": jsonable(getattr(state, "last_round_completed_at", None)),
            "pages_scanned_in_round": int(getattr(state, "pages_scanned_in_round", 0)),
            "markets_seen_in_round": int(getattr(state, "markets_seen_in_round", 0)),
            "last_completed_round_pages": int(getattr(state, "last_completed_round_pages", 0)),
            "last_completed_round_markets": int(getattr(state, "last_completed_round_markets", 0)),
            "last_page_size": int(getattr(state, "last_page_size", 0)),
            "last_tick_started_at": jsonable(getattr(state, "last_tick_started_at", None)),
            "last_tick_completed_at": jsonable(getattr(state, "last_tick_completed_at", None)),
            "last_tick_requests": int(getattr(state, "last_tick_requests", 0)),
            "last_tick_markets": int(getattr(state, "last_tick_markets", 0)),
            "last_error": getattr(state, "last_error", None),
            "consecutive_failures": int(getattr(state, "consecutive_failures", 0)),
        }

    def _market_ws_snapshot(self, token_id: str) -> OrderbookSnapshot | None:
        worker = getattr(self.runtime, "market_ws_worker", None)
        if worker is None:
            return None
        snapshot = getattr(worker, "snapshot", None)
        if not callable(snapshot):
            return None
        return snapshot(token_id)

    def _settings(self) -> Any | None:
        return getattr(self.runtime, "settings", None)
