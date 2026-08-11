# Project agent rules

This file is an agent-control file. All human-facing project documentation belongs under `docs/`.

- Before changing implementation or tests, inspect `docs/governance/change-map.yaml`.
- Update every affected authored document in the same change as the code.
- Run `python3 scripts/docs_guard.py generate` after changing document structure or machine-readable contracts.
- Run `python3 scripts/docs_guard.py check` before handing work back.
- When architecture, order execution, risk controls, or AI execution boundaries change, add or update an ADR and require human approval.
- Never change an approved policy merely to make an implementation pass. Report the conflict and fix the implementation or request a decision.
