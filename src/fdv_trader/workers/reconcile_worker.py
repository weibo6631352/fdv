from __future__ import annotations


class ReconcileWorker:
    priority = "P2"

    async def run(self) -> None:
        raise NotImplementedError("Reconcile worker is not implemented yet.")

