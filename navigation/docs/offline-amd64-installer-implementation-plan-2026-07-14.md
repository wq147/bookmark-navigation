# Bookmark Navigation Offline amd64 Installer Implementation Plan

> **For Codex:** Implement this plan sequentially with test-driven development. Run the focused deployment tests after every task and the complete application test suites before packaging.

**Goal:** Produce and verify a self-contained Linux amd64 release archive that installs or upgrades Bookmark Navigation without source code or registry access, while allowing an administrator to choose the host listen address and port.

**Architecture:** Keep the existing source-oriented Compose setup for development. Add a separate release template containing an image-only Compose file and a Bash installer. Test the installer through an isolated fake-Docker harness before exercising the same artifact against Docker on the target server. Build the application image once on the target server, export it with `docker save`, assemble a checksum-protected release directory, and compress it as `tar.gz`.

**Tech Stack:** Bash, Docker Engine, Docker Compose v2, pytest, FastAPI/Alembic, Docker image archive, SHA-256.

---

### Task 1: Define the release artifact contract with failing tests

**Files:**
- Create: `backend/tests/test_offline_installer.py`
- Create: `release/compose.yaml`
- Create: `release/install.sh`
- Create: `release/VERSION`
- Create: `release/MANIFEST`
- Create: `release/docs/DEPLOYMENT.md`

**Steps:**
1. Add tests that require an image-only Compose file, configurable bind address/port, persistent data and policy mounts, fixed application IP, health check, and no `build:` key.
2. Add tests that require installer help text and all approved CLI flags.
3. Run the focused test file and confirm it fails because the release files do not yet exist.
4. Add the smallest release skeleton necessary to satisfy the artifact-structure tests.
5. Re-run the focused tests and confirm the structure tests pass.

### Task 2: Implement input validation and preflight checks

**Files:**
- Modify: `backend/tests/test_offline_installer.py`
- Modify: `release/install.sh`

**Steps:**
1. Add subprocess tests for default values, `--listen`, `--port`, install/data paths, username, password file, and `--yes`.
2. Add failing cases for invalid ports, non-Linux/non-amd64 systems, missing Docker, missing Compose v2, unreadable password files, and invalid release checksums.
3. Use environment-overridable command paths or test-mode probes so tests can supply deterministic fake system commands without weakening production checks.
4. Implement strict Bash mode, argument parsing, validation, release-root discovery, prerequisite checks, and checksum verification.
5. Confirm validation failures happen before any fake Docker mutation.

### Task 3: Implement safe first installation

**Files:**
- Modify: `backend/tests/test_offline_installer.py`
- Modify: `release/install.sh`
- Modify: `release/compose.yaml`

**Steps:**
1. Add a fake-Docker integration harness that records `load`, `network`, `compose run`, `compose up`, `compose ps`, and `compose logs` calls.
2. Add a failing first-install test asserting data marker creation, UID/GID `10001`, protected `.env`, policy copy, `docker load`, migrations, one-time user creation, service startup, and health verification.
3. Add tests for occupied host ports and unsafe/nonempty unmarked target directories.
4. Implement network subnet selection without colliding with existing Docker networks and persist the chosen network values.
5. Implement first-install state, temporary password handling and cleanup, migrations, user creation, startup, and bounded health polling.
6. Confirm no plaintext password appears in `.env`, installer state, normal output, or recorded command arguments.

### Task 4: Implement idempotent upgrade with preserved data

**Files:**
- Modify: `backend/tests/test_offline_installer.py`
- Modify: `release/install.sh`

**Steps:**
1. Add a failing repeat-run test using an existing valid install state and data marker.
2. Assert that an upgrade loads the new image, creates a timestamped database backup, runs migrations, recreates the service, and never runs the user-creation command.
3. Add a test that explicit new listen/port values update `.env`, while omitted values retain installed values.
4. Add a test that supplied username/password options during upgrade produce a warning and do not reset credentials.
5. Implement atomic configuration writes, upgrade backup, migration, container recreation, and diagnostic output on health failure.
6. Re-run the installer tests and confirm first-install and upgrade paths both pass.

### Task 5: Add the release builder and operator documentation

**Files:**
- Create: `release/build-offline-bundle.sh`
- Modify: `backend/tests/test_offline_installer.py`
- Modify: `release/MANIFEST`
- Modify: `release/docs/DEPLOYMENT.md`
- Modify: `README.md`
- Modify: `docs/linux-server-deployment-2026-07-14.md`

**Steps:**
1. Add tests for builder arguments, required image tag, amd64 image inspection, deterministic release layout, and SHA-256 generation.
2. Implement the builder so it accepts an existing local Docker image, exports it to `image/bookmark-navigation-amd64.tar`, copies runtime files, generates checksums, and creates the versioned `tar.gz`.
3. Document prerequisites, first install, noninteractive password-file use, upgrade, port/address changes, reverse proxy setup, logs, backup locations, and troubleshooting.
4. Link the offline deployment guide from the project README and the existing server deployment record.
5. Run documentation and deployment tests.

### Task 6: Verify application and release locally

**Files:**
- Modify only if verification exposes a defect.

**Steps:**
1. Run shell syntax checks on `install.sh` and `build-offline-bundle.sh`.
2. Run all backend tests.
3. Run frontend unit tests and production build.
4. Run `docker compose config` against the release Compose file with representative environment values where Docker tooling is available.
5. Inspect the generated release tree and verify `SHA256SUMS` from within that tree.

### Task 7: Build and test the offline artifact on the target server

**Files:**
- Server output: versioned release directory and `bookmark-navigation-offline-amd64-<version>.tar.gz`
- Local copy: repository root release archive, intentionally left untracked unless the user requests committing binaries.

**Steps:**
1. SSH to `deploy@example.com` using an approved key.
2. Copy the release runtime templates to a staging directory without modifying the live data directory.
3. Confirm the running image is Linux amd64 and export it with `docker save` through the release builder.
4. Verify the archive checksums and inspect the archive contents.
5. Exercise a fresh installation in an isolated server directory with a separate Compose project/network and unused host port.
6. Create a sentinel application/data record, rerun the installer as an upgrade with another port, and confirm the record and account remain present and an upgrade backup exists.
7. Remove only the isolated test deployment after verification; do not alter the live Bookmark Navigation deployment.
8. Copy the verified archive back into the knowledge-vault root and record its SHA-256.

### Task 8: Final verification and checkpoint

**Files:**
- Modify only documentation or tests if final verification exposes a discrepancy.

**Steps:**
1. Re-run focused installer tests and the relevant full suites from a clean shell.
2. Confirm the live server remains healthy and its original bind address, port, image, and data directory are unchanged.
3. Check `git diff --check`, review the scoped diff, and ensure unrelated existing archives remain untouched.
4. Commit source, tests, release templates, and documentation; do not commit the Docker image archive or final `tar.gz` unless explicitly requested.
5. Report the commit, archive path, SHA-256, verified install/upgrade commands, and known `amd64` limitation.
