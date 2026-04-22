from __future__ import annotations

from pathlib import Path


def test_runtime_no_longer_imports_legacy_sdk() -> None:
    needle = "".join(("strategy", "_sdk"))
    roots = [Path("src/polymarket_trader"), Path("src/strategies"), Path("tests")]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if needle in text:
                offenders.append(str(path))
    assert offenders == []
