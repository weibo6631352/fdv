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
        if command.condition_id is not None and self._account_state_store is not None:
            if command.action is FrameworkCommandAction.PAUSE_MARKET:
                self._account_state_store.pause_market(command.condition_id, reason=command.reason)
            elif command.action is FrameworkCommandAction.RESUME_MARKET:
                self._account_state_store.resume_market(command.condition_id)

        return ExtensionCommandResult(
            command=command,
            action=command.action,
            accepted=True,
            trace_id=trace_id,
            reason=command.reason,
            executed_at=_utc_now(),
        )
