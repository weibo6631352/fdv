from __future__ import annotations

from pathlib import Path


FORBIDDEN_FRAMEWORK_TERMS = (
    "strategies" + "." + "current",
    "Current" + "Strategy",
    "F" + "DV",
    "fully diluted" + " valuation",
    "entry" + "_no_price",
    "exit" + "_no_price",
    "primary" + " outcome",
    "strategy" + "_filtered_out",
)


def test_framework_code_does_not_reference_current_business_terms() -> None:
    offenders: dict[str, list[str]] = {}
    for path in Path("src/polymarket_trader").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = [term for term in FORBIDDEN_FRAMEWORK_TERMS if term in text]
        if hits:
            offenders[str(path)] = hits
    assert offenders == {}


def test_app_and_domain_tests_do_not_reference_current_business_terms() -> None:
    offenders: dict[str, list[str]] = {}
    boundary_test_path = Path(__file__).resolve()
    for root in (Path("tests/app"), Path("tests/domain")):
        for path in root.rglob("*.py"):
            if path.resolve() == boundary_test_path:
                continue
            text = path.read_text(encoding="utf-8")
            hits = [term for term in FORBIDDEN_FRAMEWORK_TERMS if term in text]
            if hits:
                offenders[str(path)] = hits
    assert offenders == {}
