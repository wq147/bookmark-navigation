# Public Release Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the standalone project safe and understandable for a future public GitHub release and apply the AGPL-3.0-only license.

**Architecture:** A repository-level regression test defines the public-content boundary. Documentation and installer examples use generic identities, while optional acceptance tests consume a user-supplied fixture path and derive their expectations from that fixture. Public project metadata is kept at the repository root.

**Tech Stack:** Python 3.13.14, pytest, Bash, Vue 3, TypeScript, npm via fnm, Markdown, GNU AGPL v3.

## Global Constraints

- Work only in the standalone project root.
- Do not copy private bookmarks or secrets into the project.
- Do not run `git init`, create a GitHub repository, commit, push, or deploy.
- Keep `README_FIRST.md`, migrations, locks, source, tests, and release scripts.
- Use `uv` for Python commands and `fnm` for Node.js commands.

---

### Task 1: Encode the public-content boundary

**Files:**
- Modify: `navigation/backend/tests/test_deployment_docs.py`

**Interfaces:**
- Consumes: `BOOKMARK_ROOT` and the existing documentation-test conventions.
- Produces: `test_public_release_metadata_and_content_are_sanitized`.

- [ ] **Step 1: Add a failing test**

Add a test requiring root `README.md`, `LICENSE`, and `SECURITY.md`, requiring AGPL wording, and rejecting the audited personal SSH identity, hostname, key name, dated private fixture filename, and absolute user-home path in public source and documentation files.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -m pytest tests/test_deployment_docs.py::test_public_release_metadata_and_content_are_sanitized -q`

Expected: FAIL because public metadata is absent and known personal strings still exist.

### Task 2: Add public metadata and AGPL license

**Files:**
- Create: `README.md`
- Create: `SECURITY.md`
- Create: `LICENSE`
- Modify: `README_FIRST.md`

**Interfaces:**
- Consumes: existing project entry points and standard GNU AGPL v3 license text.
- Produces: GitHub landing page, security policy, and `AGPL-3.0-only` licensing notice.

- [ ] **Step 1: Add concise public-facing documentation**

Create a root overview that describes both project components, links to `README_FIRST.md`, lists privacy exclusions, shows the pinned `uv`/`fnm` validation commands, and states the license. Add a security policy requesting private reports without inventing a public email address.

- [ ] **Step 2: Add the standard license text**

Fetch `https://www.gnu.org/licenses/agpl-3.0.txt`, verify its title/version, and save it unmodified as `LICENSE`.

- [ ] **Step 3: Link the public files from the detailed entry**

Add links to the root public overview, security policy, and license without replacing `README_FIRST.md` as the detailed entry.

### Task 3: Generalize identities and private-fixture tests

**Files:**
- Modify: `navigation/release/install.sh`
- Modify: `navigation/release/docs/DEPLOYMENT.md`
- Modify: `navigation/README.md`
- Modify: `navigation/docs/linux-server-deployment-2026-07-14.md`
- Modify: `navigation/docs/offline-amd64-installer-design-2026-07-14.md`
- Modify: `navigation/docs/offline-amd64-installer-implementation-plan-2026-07-14.md`
- Modify: `navigation/docs/acceptance-2026-07-13.md`
- Modify: `navigation/backend/tests/test_real_v5_import.py`
- Modify: `navigation/backend/tests/test_export_backup.py`
- Modify: frontend test and E2E example identities where relevant.

**Interfaces:**
- Consumes: optional environment variable `NAV_PRIVATE_BOOKMARK_FIXTURE` containing a path to a Netscape Bookmark HTML file.
- Produces: fixture-independent acceptance tests and generic public deployment examples.

- [ ] **Step 1: Replace public identity defaults**

Use `admin` for initial administrator examples/defaults, `deploy@example.com`-style host examples, `/home/deploy` paths, and example SSH key names.

- [ ] **Step 2: Make private acceptance tests optional and data-driven**

Resolve `NAV_PRIVATE_BOOKMARK_FIXTURE` only when set, skip otherwise, and compare import/export results to bookmark and folder state parsed from the supplied fixture. Remove hard-coded fixture names and counts.

- [ ] **Step 3: Sanitize the historical acceptance report**

Keep the validation method and known regression coverage, but remove private filenames, exact personal dataset counts, and personal folder taxonomy.

- [ ] **Step 4: Run focused tests**

Run the public-content regression and both optional-fixture test modules. Expected: public-content test PASS; optional tests SKIP cleanly when the environment variable is absent.

### Task 4: Full verification

**Files:**
- Verify all modified files and generated output only; do not create release artifacts.

**Interfaces:**
- Consumes: the cleaned source tree.
- Produces: current evidence for publication readiness.

- [ ] **Step 1: Run backend verification**

Run: `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -W error -m pytest -q`

Expected: all ordinary tests pass and private-fixture tests skip when not configured.

- [ ] **Step 2: Run frontend verification**

Run via `fnm exec --using ../../.node-version`: `npm test -- --run`, `npm run typecheck`, and `npm run build`.

Expected: all three commands pass.

- [ ] **Step 3: Run static verification**

Run `bash -n` for all three release/deploy scripts, validate local Markdown links, confirm the license heading, and repeat the sensitive-content scan excluding generated dependency/build directories.

Expected: no personal infrastructure identifier, private fixture filename, credential artifact, or broken local Markdown link remains.

- [ ] **Step 4: Report the boundary**

Report changed files, license identifier, test results, remaining historical-only references if any, and explicitly state that Git initialization and GitHub publication were not performed.
