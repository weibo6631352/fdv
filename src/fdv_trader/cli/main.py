from __future__ import annotations

import argparse
from collections.abc import Sequence

from fdv_trader.main import main as run_service


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fdv-trader")
    parser.add_argument("command", nargs="?", default="run", choices=["run"])
    parser.parse_args(argv)
    run_service()


if __name__ == "__main__":
    main()

