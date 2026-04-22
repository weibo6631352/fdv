# Extension API Refactor Completion Record

Status: executed.

This record replaces the long task-by-task implementation plan so future codebase scans do not treat completed checklist items as pending work.

## Completed Shape

- Public secondary-development contracts live under `src/polymarket_trader/extension_api/`.
- Current FDV business behavior lives under `src/strategies/current/`.
- The legacy strategy contract package and references were removed.
- Framework code calls extensions through neutral host/context/decision APIs instead of embedding current-strategy policy.
- Old architecture tests that only preserved legacy package names or single-strategy assumptions were deleted or rewritten around extension boundaries.

## Historical Detail

The full checklist was removed from live docs after execution. Use git history only if historical implementation detail is needed.
