# Bookmark Navigation Local Development Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the standalone project's local Python and Node.js environments with uv and fnm, using exact interpreter versions and existing dependency declarations.

**Architecture:** Root version files select Python 3.13.14 and Node.js 24.18.0. The backend uses uv to create `navigation/backend/.venv` and generate `navigation/backend/uv.lock`; the frontend uses fnm-selected npm with the existing `package-lock.json`.

**Tech Stack:** uv 0.11.30, CPython 3.13.14, fnm 1.39.0, Node.js 24.18.0, npm 11.16.0, pytest, Vitest, vue-tsc, Vite.

## Global Constraints

- Remove old generated environments before initialization.
- Do not initialize or modify Git metadata.
- Do not copy private bookmark fixtures or other personal data.
- Use `/tmp/bookmark-navigation-uv-cache` for uv cache writes in the sandbox.

---

### Task 1: Remove old environments and pin runtimes

**Files:**
- Create: `.python-version`
- Create: `.node-version`

**Interfaces:**
- Consumes: installed uv Python 3.13.14 and fnm Node.js 24.18.0.
- Produces: exact runtime selection for the backend and frontend initialization tasks.

- [x] List all removable generated paths and verify every path is under the standalone target root.
- [x] Remove the listed Python, Node.js, test, and build artifacts.
- [x] Write `3.13.14` to `.python-version` and `v24.18.0` to `.node-version`.
- [x] Verify `uv python find 3.13.14` and `fnm exec --using .node-version node --version` select the pinned versions.

### Task 2: Initialize the backend with uv

**Files:**
- Create: `navigation/backend/.venv/`
- Create: `navigation/backend/uv.lock`

**Interfaces:**
- Consumes: `.python-version` and `navigation/backend/pyproject.toml`.
- Produces: a locked backend dependency graph and runnable local Python environment.

- [x] Run `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --python 3.13.14 --extra test` from `navigation/backend`.
- [x] Verify `.venv/bin/python --version` is Python 3.13.14.
- [x] Run `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -m pytest -q`; the subsequently identified Python 3.13 SQLite `ResourceWarning` was resolved by the dedicated connection-lifecycle plan.

### Task 3: Initialize the frontend with fnm

**Files:**
- Create: `navigation/frontend/node_modules/`
- Preserve: `navigation/frontend/package-lock.json`

**Interfaces:**
- Consumes: `.node-version`, `navigation/frontend/package.json`, and `navigation/frontend/package-lock.json`.
- Produces: a clean npm dependency installation under Node.js 24.18.0.

- [x] Run `fnm exec --using ../../.node-version npm ci` from `navigation/frontend`.
- [x] Verify Node.js reports `v24.18.0` and npm reports `11.16.0` under the same fnm context.
- [x] Run `npm test -- --run`, `npm run typecheck`, and `npm run build` through `fnm exec`.

### Task 4: Verify environment boundaries

**Files:**
- Verify: `.gitignore`
- Verify: `.python-version`
- Verify: `.node-version`
- Verify: `navigation/backend/uv.lock`

**Interfaces:**
- Consumes: outputs from Tasks 1 through 3.
- Produces: evidence that the new environments are reproducible and isolated from the original knowledge vault.

- [x] Confirm the target remains outside Git with `git rev-parse --is-inside-work-tree` returning non-zero.
- [x] Confirm `.venv`, `node_modules`, `dist`, caches, and databases are covered by `.gitignore`.
- [x] Search runtime and build files for absolute dependencies on the original private knowledge-base path.
- [x] Report exact tool versions, dependency installation results, test counts, and any skipped validation.
