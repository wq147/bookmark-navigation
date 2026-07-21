# SQLite Connection Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explicitly close every native SQLite connection and dispose every test-owned SQLAlchemy engine so the Python 3.13.14 backend suite passes with global `-W error`.

**Architecture:** Add one `_connect_sqlite()` context helper in `backup_service.py` using `contextlib.closing`, then route every production raw SQLite connection through it. Test-only raw connections use `closing()` directly, and test-owned engines use deterministic `dispose()` cleanup.

**Tech Stack:** Python 3.13.14, uv 0.11.30, sqlite3, SQLAlchemy 2.0, pytest 9.1.1.

## Global Constraints

- Do not suppress `ResourceWarning`.
- Do not modify Alembic migration history.
- Do not change backup, restore, transaction, or API behavior.
- Do not initialize Git or upgrade dependencies.

---

### Task 1: Add a failing raw-connection regression test

**Files:**
- Modify: `navigation/backend/tests/test_export_backup.py`

**Interfaces:**
- Consumes: `create_backup(session, reason)` and the real sqlite3 connection factory.
- Produces: a regression test that observes whether every connection opened by `create_backup()` receives `close()`.

- [x] Add a `TrackingConnection(sqlite3.Connection)` test subclass whose `close()` method records closure before calling `super().close()`.
- [x] Monkeypatch `app.backup_service.sqlite3.connect` to create and collect tracking connections.
- [x] Call `create_backup()` against the real fixture database and assert exactly two raw connections were opened and both were closed.
- [x] Run the new test with `-W error`; expected result before the fix is an assertion failure because both `was_closed` values are false.

### Task 2: Close production raw SQLite connections

**Files:**
- Modify: `navigation/backend/app/backup_service.py`
- Test: `navigation/backend/tests/test_export_backup.py`

**Interfaces:**
- Consumes: file-backed SQLite paths.
- Produces: `_connect_sqlite(path)` returning a context manager that always calls `Connection.close()`.

- [x] Import `AbstractContextManager` and `closing` from `contextlib`.
- [x] Implement `_connect_sqlite(path)` as `closing(sqlite3.connect(path))`.
- [x] Replace all five production `with sqlite3.connect(...)` sites with `_connect_sqlite(...)` while retaining current explicit commits.
- [x] Re-run the new regression test; expected result is one passed test with no warning.
- [x] Run the backup and restore test module under global `-W error`.

### Task 3: Close test-owned SQLite and SQLAlchemy resources

**Files:**
- Modify: `navigation/backend/tests/test_export_backup.py`
- Modify: `navigation/backend/tests/test_models.py`

**Interfaces:**
- Consumes: test-created SQLite connections and SQLAlchemy engines.
- Produces: deterministic cleanup on successful and exceptional test paths.

- [x] Wrap the two direct test `sqlite3.connect()` contexts with `closing()`.
- [x] Ensure the shared models session fixture disposes its engine in `finally`.
- [x] Ensure the pragma and cross-thread model tests dispose their engines in `finally`.
- [x] Run `tests/test_export_backup.py tests/test_models.py -W error`; expected result is all selected tests passing, except the existing private V5 skip.

### Task 4: Complete strict validation

**Files:**
- Verify: `navigation/backend/app/backup_service.py`
- Verify: `navigation/backend/tests/test_export_backup.py`
- Verify: `navigation/backend/tests/test_models.py`
- Verify: `navigation/docs/superpowers/specs/README.md`
- Verify: `navigation/docs/superpowers/plans/README.md`

**Interfaces:**
- Consumes: Tasks 1 through 3.
- Produces: strict Python 3.13 validation evidence and discoverable documentation.

- [x] Confirm no direct `with sqlite3.connect` remains in the backend.
- [x] Run the full backend suite with global `-W error`; expected result is `152 passed, 2 skipped`.
- [x] Run the frontend unit tests, typecheck, and production build.
- [x] Validate Markdown relative links and shell script syntax.
- [x] Record the design and plan in their existing superpowers indexes.
