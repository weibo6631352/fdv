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
        if not isinstance(command.action, FrameworkCommandAction):
            return self._result(command, trace_id=trace_id, accepted=False, reason="invalid_command_action")

        if command.action is FrameworkCommandAction.TRIGGER_RECONCILE:
            return self._result(command, trace_id=trace_id, accepted=True, reason=command.reason)

        if command.action not in {FrameworkCommandAction.PAUSE_MARKET, FrameworkCommandAction.RESUME_MARKET}:
            return self._result(command, trace_id=trace_id, accepted=False, reason="unsupported_command")

        if command.condition_id is None:
            return self._result(command, trace_id=trace_id, accepted=False, reason="missing_condition_id")

        if self._account_state_store is None:
            return self._result(command, trace_id=trace_id, accepted=False, reason="missing_account_state_store")

        if command.action is FrameworkCommandAction.PAUSE_MARKET:
            self._account_state_store.pause_market(command.condition_id, reason=command.reason)
        else:
            self._account_state_store.resume_market(command.condition_id)

        return self._result(command, trace_id=trace_id, accepted=True, reason=command.reason)

    def _result(
        self,
        command: ExtensionCommand,
        *,
        trace_id: str,
        accepted: bool,
        reason: str,
    ) -> ExtensionCommandResult:
        return ExtensionCommandResult(
            command=command,
            action=command.action,
            accepted=accepted,
            trace_id=trace_id,
            reason=reason,
            executed_at=_utc_now(),
        )
