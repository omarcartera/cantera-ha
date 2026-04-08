# AGENTS.md — cantera-ha Project Agent Instructions

This file is the authoritative instruction set for all AI agents and models working in this repository. Read it in full before making any changes.

---

## Identity

**Project**: cantera-ha — Home Assistant custom integration for the CANtera OBD-II diagnostic suite  
**Stack**: Python · Home Assistant custom component  
**Companion repo**: `cantera` (Rust/Tauri backend, SSE API server)  
**Test runner**: `pytest` with `pytest-cov` — run via `./scripts/run_tests.sh`

---

## LAW 1 — Branch Chaining (MANDATORY)

**All feature branches MUST be chained on top of each other, never all branched independently from `main`.**

The correct topology is a linear stack:

```
main → feature/A → feature/B → feature/C → feature/D
```

**NOT** a fan-out from main:

```
main ─┬─ feature/A   ❌
      ├─ feature/B   ❌
      ├─ feature/C   ❌
      └─ feature/D   ❌
```

### Rules

1. The **first** feature branch in a batch is based on `main`.
2. Every subsequent feature branch MUST be based on the **previous** feature branch, not on `main`.
3. When work on a new feature begins, run `git checkout -b feature/<name> feature/<previous>` — never `git checkout -b feature/<name> main` (unless it is truly the first branch in a new batch).
4. If branches were accidentally created off `main` independently, they MUST be rebased into a linear chain before any code review or merge.
5. After rebasing, always force-push with `git push --force-with-lease` and verify `git log --oneline --graph` shows a single linear history.

### Why

Chained branches allow incremental PRs that build on each other, prevent re-implementing constants or helpers that a previous branch already introduced, and make the full diff reviewable as a progressive stack.

---

## LAW 2 — Zero Warnings, All Tests Pass

Before committing:

```bash
./scripts/run_tests.sh
```

All tests MUST pass and coverage MUST meet the threshold defined in `pyproject.toml`.

---

## LAW 3 — Health Endpoint First

Any code that tests connectivity to the CANtera API MUST use `/api/health` — **never** the SSE `/events` stream.

`/api/health` returns immediately with a JSON body. The SSE stream blocks indefinitely and must not be used for connection tests or polling.

---

## LAW 4 — Branch & Commit Discipline

- Create a feature branch BEFORE writing any code. No commits to `main` directly.
- Branch naming: `feature/<description>`.
- Every commit co-authored by agents MUST include:  
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- Rebase (not merge) onto the previous branch before PR.

---

## Quick Reference

```bash
# Run tests with coverage
./scripts/run_tests.sh

# Create a chained branch (correct pattern)
git checkout -b feature/new-thing feature/previous-thing

# Verify linear chain
git log --oneline --graph feature/A feature/B feature/C main

# Rebase a branch onto the previous one
git checkout feature/B
git rebase feature/A
git push --force-with-lease origin feature/B
```

**Key files:**
- `custom_components/cantera/const.py` — all constants (endpoints, timeouts, thresholds)
- `custom_components/cantera/coordinator.py` — SSE client + health poll
- `custom_components/cantera/binary_sensor.py` — API Connection + CAN Connection sensors
- `custom_components/cantera/config_flow.py` — setup flow with `ConnectionResult` enum
- `tests/` — pytest suite; run with `./scripts/run_tests.sh`
