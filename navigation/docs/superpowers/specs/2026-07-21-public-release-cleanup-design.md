# Public Release Cleanup Design

## Goal

Prepare the standalone source tree for a public GitHub repository without publishing it yet. Remove personal infrastructure identifiers and private fixture assumptions, add a GitHub-facing entry point and security policy, and license the project under AGPL-3.0-only.

## Public boundary

- Keep source code, migrations, tests, deployment scripts, and historical design records.
- Do not include private bookmark HTML, databases, backups, `.env` files, credentials, server keys, or release archives.
- Replace real usernames, hostnames, home paths, key names, and private fixture filenames with clearly generic examples.
- Historical documents may explain prior design decisions, but must not expose personal infrastructure identifiers or dataset-specific acceptance results.
- Private-fixture tests remain optional and read their input only from `NAV_PRIVATE_BOOKMARK_FIXTURE`; no private data is copied into the repository.

## Documentation and licensing

- Add root `README.md` as the GitHub landing page while retaining `README_FIRST.md` as the detailed project entry.
- Add `SECURITY.md` with private vulnerability-reporting guidance and supported-version expectations.
- Add the unmodified GNU Affero General Public License version 3 text as `LICENSE` and identify the project as `AGPL-3.0-only`.
- Use `admin` for public deployment examples and initial installer defaults.

## Verification

- Add a regression test that scans tracked source/documentation areas for the known personal identifiers and private fixture filename.
- Verify optional fixture tests derive expectations from the supplied fixture rather than hard-coded personal counts.
- Run the complete backend suite with warnings treated as errors, frontend unit tests/typecheck/build, shell syntax checks, Markdown relative-link checks, and a final sensitive-content scan.
- Do not initialize Git, create a GitHub repository, commit, push, or deploy in this phase.
