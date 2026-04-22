from __future__ import annotations

from importlib import import_module
from types import ModuleType

from polymarket_trader.extension_api import (
    BusinessExtension as StrategyModule,
    ExtensionLoadError,
    ExtensionManifest as StrategyManifest,
    StrategyPorts,
)


def load_strategy(
    *,
    module_path: str,
    ports: StrategyPorts | None = None,
    config_path: str | None = None,
) -> StrategyModule:
    manifest = load_strategy_manifest(module_path)
    strategy = manifest.factory(ports=ports, config_path=config_path)
    if not isinstance(strategy, StrategyModule):
        raise ExtensionLoadError(
            f"strategy factory '{manifest.module_path}' did not return a StrategyModule-compatible object"
        )
    return strategy


def load_strategy_manifest(module_path: str) -> StrategyManifest:
    module = import_module(module_path)
    manifest = _extract_manifest(module)
    if manifest is not None:
        return manifest
    try:
        manifest_module = import_module(f"{module_path}.manifest")
    except ModuleNotFoundError as exc:
        raise ExtensionLoadError(
            f"strategy module '{module_path}' does not expose a manifest"
        ) from exc
    manifest = _extract_manifest(manifest_module)
    if manifest is None:
        raise ExtensionLoadError(f"strategy module '{module_path}' does not expose a valid manifest")
    return manifest


def _extract_manifest(module: ModuleType) -> StrategyManifest | None:
    manifest = getattr(module, "manifest", None)
    if isinstance(manifest, StrategyManifest):
        return manifest
    return None
