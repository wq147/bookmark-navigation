# Bookmark Documentation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `30-资源/工具/书签管理/README_FIRST.md` the single project entry point, document the purpose of all important project and release files, remove two obsolete local debug archives, and commit the verified documentation changes.

**Architecture:** Keep one short global entry document and route detailed operations to responsibility-specific documents. Add automated assertions for the required responsibility descriptions and run a local Markdown-link checker so future edits cannot silently remove the navigation contract.

**Tech Stack:** Markdown, Python/pytest, Git, SHA-256.

## Global Constraints

- Only modify local files under `30-资源/工具/书签管理` plus the two obsolete local archive files in the repository root.
- Do not log in to or modify the Linux server.
- Keep `bookmark-navigation-offline-amd64-2026.07.14-r2.tar.gz` untracked and preserve SHA-256 `0ca915514747416311ee40948750523d45931fe6df9a4f4468d7af0c6974dc7f`.
- Do not modify application business code.
- Do not stage unrelated `00-收件箱/Ubuntu_SSH密钥登录与NOPASSWD_sudo安全配置_SOP.md`.

---

### Task 1: Define the documentation contract in tests

**Files:**
- Modify: `navigation/backend/tests/test_deployment_docs.py`
- Test: `navigation/backend/tests/test_deployment_docs.py`

**Interfaces:**
- Consumes: the approved responsibility lists in `navigation/docs/superpowers/specs/2026-07-14-bookmark-documentation-consolidation-design.md`.
- Produces: pytest assertions that require the main entry, source guide, offline guide, and historical record labels.

- [ ] **Step 1: Add failing assertions for the main entry**

Require `README_FIRST.md` to name `bookmark_policy.json`, all three maintenance scripts, the V5 HTML sample, `navigation/`, the final offline archive, and the four usage scenarios.

- [ ] **Step 2: Add failing assertions for specialist documents**

Require `navigation/README.md` to identify itself as the source-build/advanced-operations guide and name `backend/`, `frontend/`, `Dockerfile`, `compose.yaml`, `.env.example`, `deploy/`, `release/`, and `docs/`. Require the release guide to name all eight bundle artifacts, and require the 2026-07-14 deployment record to contain the phrase `历史部署记录`.

- [ ] **Step 3: Run the focused tests and confirm failure**

Run:

```bash
cd 30-资源/工具/书签管理/navigation
backend/venv/bin/pytest -q backend/tests/test_deployment_docs.py
```

Expected: one or more new responsibility-contract assertions fail against the current documents.

### Task 2: Rewrite the single entry and clarify specialist documents

**Files:**
- Modify: `README_FIRST.md`
- Modify: `navigation/README.md`
- Modify: `navigation/release/docs/DEPLOYMENT.md`
- Modify: `navigation/docs/linux-server-deployment-2026-07-14.md`
- Test: `navigation/backend/tests/test_deployment_docs.py`

**Interfaces:**
- Consumes: the failing assertions from Task 1.
- Produces: one global entry point and three clearly bounded specialist documents.

- [ ] **Step 1: Rewrite `README_FIRST.md`**

Use this section order: project purpose, four scenario shortcuts, recommended offline installation command, top-level file responsibility table, `navigation/` responsibility summary, document map, daily bookmark workflow, current accepted artifacts, and safety notes.

- [ ] **Step 2: Clarify `navigation/README.md`**

Change the title and introduction to mark it as the source-build and advanced-operations guide. Insert a responsibility table for `backend/`, `frontend/`, `Dockerfile`, `compose.yaml`, `.env.example`, `deploy/`, `release/`, and `docs/`; keep its existing source-mode operational commands intact.

- [ ] **Step 3: Document every offline bundle artifact**

Add a table near the beginning of `release/docs/DEPLOYMENT.md` covering `install.sh`, `compose.yaml`, `image/bookmark-navigation-amd64.tar`, `config/bookmark_policy.json`, `VERSION`, `MANIFEST`, `SHA256SUMS`, and `docs/DEPLOYMENT.md`.

- [ ] **Step 4: Mark the server record as historical**

Change the 2026-07-14 record title/introduction so it is visibly a `历史部署记录`, while retaining its factual commands and linking to the recommended offline guide.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
cd 30-资源/工具/书签管理/navigation
backend/venv/bin/pytest -q backend/tests/test_deployment_docs.py
```

Expected: all deployment-document tests pass.

### Task 3: Verify links and remove obsolete local archives

**Files:**
- Delete: `bookmark-navigation-deploy-20260714.tar.gz`
- Delete: `bookmark-navigation-deploy-20260714-r2.tar.gz`
- Preserve: `bookmark-navigation-offline-amd64-2026.07.14-r2.tar.gz`

**Interfaces:**
- Consumes: the completed documentation set from Task 2.
- Produces: a clean local handoff with valid links and only the final archive retained.

- [ ] **Step 1: Check all local Markdown links under the bookmark project**

Run a Python script that extracts non-HTTP Markdown link targets, resolves each target relative to its containing document, ignores anchors, and exits nonzero for missing paths.

Expected: zero missing local link targets.

- [ ] **Step 2: Verify the final archive before cleanup**

Run:

```bash
shasum -a 256 bookmark-navigation-offline-amd64-2026.07.14-r2.tar.gz
```

Expected:

```text
0ca915514747416311ee40948750523d45931fe6df9a4f4468d7af0c6974dc7f
```

- [ ] **Step 3: Delete only the two obsolete debug archives**

Remove the two exact `bookmark-navigation-deploy-20260714*.tar.gz` paths. Confirm the final offline archive and unrelated inbox SOP still exist.

### Task 4: Full verification and Git checkpoint

**Files:**
- Stage only the documentation, documentation tests, design, and implementation plan.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean, evidence-backed Git commit with binary archives excluded.

- [ ] **Step 1: Run full backend regression**

Run:

```bash
cd 30-资源/工具/书签管理/navigation/backend
venv/bin/pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Validate whitespace and repository scope**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the intended documentation/test changes, the unrelated inbox SOP, and the retained final archive are visible.

- [ ] **Step 3: Stage the intended text files**

Stage `README_FIRST.md`, the three specialist documents, `test_deployment_docs.py`, this plan, and any approved spec correction. Do not stage any `tar.gz` or unrelated inbox file.

- [ ] **Step 4: Review staged scope and commit**

Run:

```bash
git diff --cached --check
git diff --cached --stat
git commit -m "docs(bookmarks): consolidate project documentation"
```

Expected: commit succeeds and contains no binary archive or unrelated file.
