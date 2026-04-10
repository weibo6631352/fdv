from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Gauge:
    name: str
    value: float = 0.0

    def set(self, value: float) -> None:
        self.value = value

