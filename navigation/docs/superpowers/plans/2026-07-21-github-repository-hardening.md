# GitHub Repository Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible backend/frontend Pull Request checks, protect `main` with a solo-maintainer Ruleset, and enable GitHub dependency and vulnerability-reporting safeguards.

**Architecture:** A single least-privilege GitHub Actions workflow exposes stable `Backend` and `Frontend` status checks. Repository-level regression tests validate Markdown links and the workflow contract before the workflow is pushed. GitHub Ruleset and security settings are enabled only after the checks have succeeded once, followed by a harmless documentation Pull Request that proves the gate works end to end.

**Tech Stack:** GitHub Actions, Python `3.13.14`, uv `0.11.30`, pytest, Node.js `v24.18.0`, npm, Vitest, vue-tsc, Vite, Bash, GitHub Rulesets and Advanced Security settings.

## Global Constraints

- Work on `chore/github-repository-hardening`; do not implement directly on `main`.
- The repository has one maintainer, so Pull Requests are required but required approvals remain `0`.
- CI must use `navigation/backend/uv.lock` and `navigation/frontend/package-lock.json` without updating dependencies.
- Workflow permissions must remain `contents: read`.
- Required status names are exactly `Backend` and `Frontend`.
- Do not add Docker, Playwright E2E, deployment, offline-bundle build, CodeQL, third-party security scanners, version releases or Dependabot version-update scheduling.
- Do not add credentials, a real `.env`, private bookmark fixtures, SQLite data, backups or release archives.
- GitHub settings are enabled only after the first CI run succeeds; do not configure required checks that GitHub has not registered.

---

### Task 1: Add a repository-wide Markdown link regression test

**Files:**
- Create: `navigation/backend/tests/test_markdown_links.py`

**Interfaces:**
- Consumes: repository Markdown files and local relative link targets.
- Produces: `find_broken_local_markdown_links(root: Path) -> list[str]`, used by three pytest cases and the `Backend` CI Job.

- [ ] **Step 1: Write the failing tests**

Create `navigation/backend/tests/test_markdown_links.py` with the tests first and no helper implementation:

```python
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]


def test_link_checker_reports_missing_local_target(tmp_path):
    (tmp_path / "README.md").write_text("[missing](docs/missing.md)\n")

    assert find_broken_local_markdown_links(tmp_path) == [
        "README.md -> docs/missing.md"
    ]


def test_link_checker_ignores_fenced_code_examples(tmp_path):
    (tmp_path / "README.md").write_text(
        "```markdown\n[example](docs/not-a-real-link.md)\n```\n"
    )

    assert find_broken_local_markdown_links(tmp_path) == []


def test_repository_markdown_links_resolve():
    assert find_broken_local_markdown_links(REPOSITORY_ROOT) == []
```

- [ ] **Step 2: Run the focused tests and confirm the expected failure**

Run from `navigation/backend`:

```bash
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -m pytest \
  tests/test_markdown_links.py -q
```

Expected: all three tests fail with `NameError: name 'find_broken_local_markdown_links' is not defined`.

- [ ] **Step 3: Implement the link scanner above the tests**

Replace the file with:

```python
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).parents[3]
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "playwright-report",
    "test-results",
    "venv",
}
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
FENCED_CODE = re.compile(r"```.*?```", flags=re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", 1)[0])


def find_broken_local_markdown_links(root: Path) -> list[str]:
    root = root.resolve()
    broken = []
    for document in root.rglob("*.md"):
        if IGNORED_PARTS.intersection(document.parts):
            continue
        content = FENCED_CODE.sub("", document.read_text(errors="replace"))
        content = INLINE_CODE.sub("", content)
        for raw_target in MARKDOWN_LINK.findall(content):
            target = _link_target(raw_target)
            if not target or urlsplit(target).scheme:
                continue
            resolved = (document.parent / target).resolve()
            label = f"{document.relative_to(root)} -> {target}"
            if not resolved.is_relative_to(root) or not resolved.exists():
                broken.append(label)
    return sorted(broken)


def test_link_checker_reports_missing_local_target(tmp_path):
    (tmp_path / "README.md").write_text("[missing](docs/missing.md)\n")

    assert find_broken_local_markdown_links(tmp_path) == [
        "README.md -> docs/missing.md"
    ]


def test_link_checker_ignores_fenced_code_examples(tmp_path):
    (tmp_path / "README.md").write_text(
        "```markdown\n[example](docs/not-a-real-link.md)\n```\n"
    )

    assert find_broken_local_markdown_links(tmp_path) == []


def test_repository_markdown_links_resolve():
    assert find_broken_local_markdown_links(REPOSITORY_ROOT) == []
```

- [ ] **Step 4: Run the focused and complete backend suites**

Run from `navigation/backend`:

```bash
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -m pytest \
  tests/test_markdown_links.py -q

UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -W error -m pytest -q
```

Expected: the focused file passes both tests; the full suite passes with the two repository-external private-fixture tests skipped.

- [ ] **Step 5: Commit the link regression test**

```bash
git add navigation/backend/tests/test_markdown_links.py
git commit -m "test: validate repository markdown links"
```

Expected: one commit containing only the new test file.

### Task 2: Add a tested core CI workflow

**Files:**
- Modify: `navigation/backend/tests/test_deployment_docs.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `.python-version`, `.node-version`, backend/frontend lock files and the test commands documented in `AGENTS.md`.
- Produces: stable GitHub status checks named `Backend` and `Frontend`.

- [ ] **Step 1: Add a failing workflow-contract test**

Append to `navigation/backend/tests/test_deployment_docs.py`:

```python
def test_core_ci_workflow_matches_the_repository_contract():
    workflow = (BOOKMARK_ROOT / ".github/workflows/ci.yml").read_text()

    for required in (
        "name: Backend",
        "name: Frontend",
        "permissions:",
        "contents: read",
        'version: "0.11.30"',
        'python-version: "3.13.14"',
        "uv sync --extra test --frozen",
        "python -W error -m pytest -q",
        "bash -n navigation/deploy/navigation-ops.sh",
        "node-version-file: .node-version",
        "cache-dependency-path: navigation/frontend/package-lock.json",
        "npm ci",
        "npm test -- --run",
        "npm run typecheck",
        "npm run build",
    ):
        assert required in workflow

    for excluded in (
        "playwright",
        "docker compose",
        "build-offline-bundle.sh",
        "pull-requests: write",
        "contents: write",
    ):
        assert excluded not in workflow.lower()
```

- [ ] **Step 2: Run the contract test and confirm the expected failure**

Run from `navigation/backend`:

```bash
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -m pytest \
  tests/test_deployment_docs.py::test_core_ci_workflow_matches_the_repository_contract -q
```

Expected: FAIL with `FileNotFoundError` for `.github/workflows/ci.yml`.

- [ ] **Step 3: Create the minimal workflow**

Create `.github/workflows/ci.yml` exactly as follows. The Action SHAs correspond to `actions/checkout` v6.1.0, `astral-sh/setup-uv` v8.1.0 and `actions/setup-node` v6.5.0 at plan-writing time.

```yaml
name: CI

on:
  pull_request:
    branches:
      - main
  push:
    branches:
      - main

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    name: Backend
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
      - name: Set up uv and Python
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.11.30"
          python-version: "3.13.14"
          enable-cache: true
          cache-dependency-glob: navigation/backend/uv.lock
          working-directory: navigation/backend
      - name: Install backend dependencies
        working-directory: navigation/backend
        run: uv sync --extra test --frozen
      - name: Run backend tests
        working-directory: navigation/backend
        run: uv run --extra test --frozen python -W error -m pytest -q
      - name: Validate shell scripts
        run: >-
          bash -n navigation/deploy/navigation-ops.sh
          navigation/release/install.sh
          navigation/release/build-offline-bundle.sh

  frontend:
    name: Frontend
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
      - name: Set up Node.js
        uses: actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38 # v6.5.0
        with:
          node-version-file: .node-version
          cache: npm
          cache-dependency-path: navigation/frontend/package-lock.json
      - name: Install frontend dependencies
        working-directory: navigation/frontend
        run: npm ci
      - name: Run frontend unit tests
        working-directory: navigation/frontend
        run: npm test -- --run
      - name: Run frontend typecheck
        working-directory: navigation/frontend
        run: npm run typecheck
      - name: Build frontend
        working-directory: navigation/frontend
        run: npm run build
```

- [ ] **Step 4: Run the workflow contract and YAML checks**

Run:

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -m pytest \
  tests/test_deployment_docs.py::test_core_ci_workflow_matches_the_repository_contract -q
cd ../..
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml"); puts "CI_YAML_OK"'
```

Expected: pytest PASS and `CI_YAML_OK`.

- [ ] **Step 5: Run all local equivalents of both Jobs**

Run:

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --extra test --frozen
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test --frozen python -W error -m pytest -q

cd ../frontend
fnm exec --using ../../.node-version npm ci
fnm exec --using ../../.node-version npm test -- --run
fnm exec --using ../../.node-version npm run typecheck
fnm exec --using ../../.node-version npm run build

cd ../..
bash -n navigation/deploy/navigation-ops.sh \
  navigation/release/install.sh \
  navigation/release/build-offline-bundle.sh
git diff --check
```

Expected: all commands exit `0`; private-fixture tests are the only backend skips; no whitespace errors are reported.

- [ ] **Step 6: Remove regenerated ignored artifacts and confirm the index boundary**

List and remove only:

```bash
find navigation -type d \( \
  -name .venv -o -name node_modules -o -name dist -o \
  -name .pytest_cache -o -name __pycache__ -o \
  -name test-results -o -name playwright-report \
\) -prune -print
```

After confirming every result is under this repository, remove those generated paths and run:

```bash
git status --short
git diff --check
```

Expected: only `.github/workflows/ci.yml` and `navigation/backend/tests/test_deployment_docs.py` are modified for this task.

- [ ] **Step 7: Commit the core workflow**

```bash
git add .github/workflows/ci.yml navigation/backend/tests/test_deployment_docs.py
git commit -m "ci: add core pull request checks"
```

Expected: one commit containing the workflow and its contract test.

### Task 3: Push the branch and merge the first CI Pull Request

**Files:**
- No new local files; this task publishes the existing branch and creates a GitHub Pull Request.

**Interfaces:**
- Consumes: branch `chore/github-repository-hardening` with the design, plan, Markdown test and CI commits.
- Produces: GitHub Pull Request checks registered as `Backend` and `Frontend`, followed by their merge into `main`.

- [ ] **Step 1: Rebase the feature branch onto the latest remote `main`**

```bash
git fetch origin
git rebase origin/main
```

Expected: a clean rebase with no unrelated changes. If conflicts occur, stop and review them rather than force-pushing blindly.

- [ ] **Step 2: Push the feature branch**

```bash
git push -u origin chore/github-repository-hardening
```

Expected: the remote branch is created without force push.

- [ ] **Step 3: Create the Pull Request**

Open:

```text
https://github.com/wq147/bookmark-navigation/compare/main...chore/github-repository-hardening?expand=1
```

Use title:

```text
ci: add core pull request checks
```

Use body:

```markdown
## Summary

- add repository-wide Markdown relative-link regression coverage
- add least-privilege Backend and Frontend CI jobs
- document the solo-maintainer Ruleset and security-settings rollout

## Local verification

- backend full pytest with warnings as errors
- frontend Vitest, typecheck and production build
- Bash syntax checks and Git whitespace check

## Deferred

- Docker and Playwright E2E
- deployment and offline bundle publication
- GitHub Release
```

- [ ] **Step 4: Wait for both checks and inspect failures before merging**

Expected on the Pull Request:

```text
Backend: Success
Frontend: Success
```

If either check fails, inspect its logs, reproduce the failing command locally, fix it on the same branch, rerun the complete local equivalent, commit, and push. Do not enable the Ruleset or merge while a check is failing.

- [ ] **Step 5: Merge with a linear-history-compatible method**

Use **Squash and merge** or **Rebase and merge**, then confirm GitHub Actions also starts the `push` run on `main` and both Jobs succeed.

- [ ] **Step 6: Synchronize local `main`**

```bash
git switch main
git pull --ff-only origin main
```

Expected: local `main` matches `origin/main` and `git status --short --branch` is clean.

### Task 4: Enable the `main` Ruleset and repository security settings

**Files:**
- No repository file changes; this task modifies GitHub repository settings.

**Interfaces:**
- Consumes: successful `Backend` and `Frontend` check names registered on GitHub.
- Produces: active `Protect main` Ruleset and enabled GitHub security features.

- [ ] **Step 1: Create the Ruleset**

Navigate to:

```text
Repository → Settings → Rules → Rulesets → New ruleset → New branch ruleset
```

Set:

```text
Ruleset name: Protect main
Enforcement status: Active
Bypass list: empty
Target branches: Include default branch
Restrict deletions: enabled
Require linear history: enabled
Require a pull request before merging: enabled
Required approvals: 0
Require status checks to pass: enabled
Required checks: Backend, Frontend
Require branches to be up to date before merging: enabled
Block force pushes: enabled
Require signed commits: disabled
```

Create the Ruleset only after both check names are selectable.

- [ ] **Step 2: Enable dependency safeguards**

Navigate to:

```text
Repository → Settings → Security → Advanced Security
```

Enable, where shown:

```text
Dependency graph
Dependabot alerts
Dependabot security updates
Secret scanning
Push protection
```

Leave Dependabot version updates and CodeQL disabled in this phase.

- [ ] **Step 3: Enable private vulnerability reporting**

On the same Advanced Security page, enable:

```text
Private vulnerability reporting
```

Then open the repository Security/Advisories page and confirm **Report a vulnerability** is available, matching `SECURITY.md`.

- [ ] **Step 4: Record the observed settings**

Verify in GitHub UI that `Protect main` is Active and that each requested security feature shows Enabled. If a named feature is unavailable for the account/repository, record the exact UI message and do not substitute a different paid feature.

### Task 5: Prove the Ruleset with a harmless documentation Pull Request

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: active Ruleset and successful CI on `main`.
- Produces: documented contributor workflow and evidence that direct push is rejected while a zero-approval PR succeeds.

- [ ] **Step 1: Create a test branch from current `main`**

```bash
git switch main
git pull --ff-only origin main
git switch -c docs/document-pull-request-workflow
```

- [ ] **Step 2: Add the workflow note**

Append to `README.md`:

```markdown
## 贡献流程

日常修改通过功能分支和 Pull Request 合并到 `main`。Pull Request 必须通过 `Backend` 与 `Frontend` 检查；Docker、Playwright E2E、部署和发布验证在对应的独立阶段执行。
```

- [ ] **Step 3: Verify and commit the documentation change**

```bash
git diff --check
git add README.md
git commit -m "docs: describe pull request workflow"
```

Expected: one documentation-only commit.

- [ ] **Step 4: Prove direct `main` updates are rejected without changing local `main`**

From `docs/document-pull-request-workflow`, run:

```bash
git push origin HEAD:main
```

Expected: non-zero exit with a GitHub repository-rule rejection. Do not disable the Ruleset in response; this failure is the expected proof.

- [ ] **Step 5: Push the branch and open the test Pull Request**

```bash
git push -u origin docs/document-pull-request-workflow
```

Open:

```text
https://github.com/wq147/bookmark-navigation/compare/main...docs/document-pull-request-workflow?expand=1
```

Use title `docs: describe pull request workflow`. Confirm no approval is required, while `Backend` and `Frontend` are required.

- [ ] **Step 6: Merge only after both checks succeed**

Expected: the Pull Request becomes mergeable with zero approvals after both checks pass and the branch is up to date. Merge with Squash or Rebase, then confirm the post-merge `main` workflow also succeeds.

- [ ] **Step 7: Synchronize and clean local branches**

```bash
git switch main
git pull --ff-only origin main
git branch -d docs/document-pull-request-workflow
git status --short --branch
```

Expected: clean `main` tracking `origin/main`. Remove the remote feature branches through GitHub after confirming both merged Pull Requests remain accessible.

### Task 6: Final acceptance report

**Files:**
- No additional files unless an unavailable GitHub feature requires a factual note in the task report.

**Interfaces:**
- Consumes: local Git state, both merged Pull Requests, their Actions runs and GitHub Settings.
- Produces: an evidence-based completion report without claiming deferred checks.

- [ ] **Step 1: Verify local repository state**

```bash
git status --short --branch
git log -3 --oneline --decorate
git remote -v
```

Expected: clean `main`, `main...origin/main` with no divergence, and only the intended GitHub origin.

- [ ] **Step 2: Verify GitHub evidence**

Record:

```text
First CI Pull Request URL and merge commit
Ruleset test Pull Request URL and merge commit
Backend and Frontend run URLs for both Pull Requests
Protect main Ruleset status
Dependency graph status
Dependabot alerts status
Dependabot security updates status
Private vulnerability reporting status
Secret scanning and push protection status, or exact unavailability message
```

- [ ] **Step 3: Report deferred verification honestly**

State that Docker, Playwright E2E, deployment, offline bundle publication, CodeQL, Dependabot version updates and GitHub Release were not executed or enabled in this phase.
