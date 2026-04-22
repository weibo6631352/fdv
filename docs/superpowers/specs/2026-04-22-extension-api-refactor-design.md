# Extension API Refactor Design Record

Status: executed.

The detailed design discussion was removed from live docs because the target architecture is now represented by code and focused docs. Keep this file as a short pointer for historical context only.

## Current Design Contract

- Framework layer owns orchestration, risk gates, runtime state, persistence adapters, and external protocol adapters.
- Extensions own business selection, sizing, entry/exit policy, and hook-driven intervention.
- Extension decisions request framework actions; they do not directly call trading clients or persistence implementations.
- Framework-facing DTOs stay strategy-neutral. Current FDV-specific thresholds, keywords, and sizing choices stay under `src/strategies/current/`.

## Historical Detail

Use git history only if historical design detail is needed.
