# Private Bookmark Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a password-protected, Docker Compose-deployable private navigation site that manages the existing hierarchical bookmark collection and safely exchanges Netscape Bookmark HTML with multiple browsers.

**Architecture:** A FastAPI monolith serves a Vue 3 SPA and a versioned JSON API. SQLAlchemy persists the canonical folder tree, bookmarks, sessions, import batches, operations, and backups in SQLite; a focused bookmark-domain package adapts the existing parser, normalizer, classifier, numbering, and audit behavior without coupling it to HTTP or the database.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Argon2 (`pwdlib`), pytest, Vue 3, TypeScript, Vite, Pinia, Vitest, Playwright, Docker Compose, SQLite.

## Global Constraints

- The server database is the only source of truth; browser files are import/export channels.
- Public access requires authentication; there is no registration or guest access.
- Import is preview-first and never infers deletion from a missing bookmark.
- Existing URLs keep server title, folder, and notes unless the user explicitly selects an overwrite.
- New URLs use `bookmark_policy.json`; uncertain classification goes to `00_待整理`.
- Export uses standard Netscape Bookmark HTML and preserves the complete numbered hierarchy.
- Bulk import, destructive folder deletion, and restore create a backup before mutation.
- Version one excludes browser extensions, multi-user sharing, tags, page archiving, and automated link checks.
- Preserve unrelated workspace changes, including `.obsidian/app.json`.

## Planned File Structure

```text
30-资源/工具/书签管理/navigation/
├── backend/
│   ├── pyproject.toml                 # Python dependencies and pytest settings
│   ├── alembic.ini                    # Migration configuration
│   ├── alembic/env.py                 # SQLAlchemy migration binding
│   ├── alembic/versions/0001_initial.py
│   ├── app/
│   │   ├── main.py                    # FastAPI assembly, middleware, static SPA
│   │   ├── config.py                  # Validated environment settings
│   │   ├── db.py                      # Engine, sessions, transaction dependency
│   │   ├── models.py                  # Persistent entities and constraints
│   │   ├── schemas.py                 # API request/response contracts
│   │   ├── security.py                # Password, session, CSRF, login throttling
│   │   ├── dependencies.py            # Current-user and CSRF dependencies
│   │   ├── bookmark_domain.py         # Parser/normalizer/tree adapter
│   │   ├── bookmark_service.py        # Folder/bookmark/search use cases
│   │   ├── import_service.py          # Preview and confirmed merge
│   │   ├── export_service.py          # HTML and JSON export
│   │   ├── backup_service.py          # Safe snapshots, restore, retention
│   │   └── routers/                   # auth, folders, bookmarks, imports, exports, backups
│   └── tests/                          # Unit, API, import/export round-trip tests
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── api.ts                     # Typed API client and CSRF handling
│   │   ├── router.ts                  # Login and authenticated application routes
│   │   ├── stores/bookmarks.ts        # Tree, result, editor, import state
│   │   ├── views/LoginView.vue
│   │   ├── views/WorkspaceView.vue
│   │   ├── views/ImportView.vue
│   │   └── components/                # Toolbar, folder tree, list, editor, dialogs
│   └── tests/                          # Vitest component/store tests
├── Dockerfile
├── compose.yaml
├── .env.example
└── README.md
```

---

### Task 1: Bootstrap the backend and isolate bookmark-domain behavior

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/pyproject.toml`
- Create: `30-资源/工具/书签管理/navigation/backend/app/__init__.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/config.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/bookmark_domain.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_bookmark_domain.py`
- Read: `30-资源/工具/书签管理/bookmark_organizer.py`
- Read: `30-资源/工具/书签管理/bookmark_numbering.py`
- Read: `30-资源/工具/书签管理/bookmark_audit.py`

**Interfaces:**
- Produces: `normalize_url(url: str) -> str`
- Produces: `parse_html(content: str) -> BookmarkTree`
- Produces: `render_html(tree: BookmarkTree) -> str`
- Produces: `iter_bookmarks(tree: BookmarkTree) -> Iterator[BookmarkRecord]`
- Produces: immutable `FolderNode`, `BookmarkNode`, `BookmarkRecord`, and `BookmarkTree` dataclasses.

- [ ] **Step 1: Write failing domain tests using the real V5 format**

```python
from app.bookmark_domain import normalize_url, parse_html, render_html

SAMPLE = '''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">书签栏</H3><DL><p>
<DT><H3>02_AI 与智能开发</H3><DL><p>
<DT><A HREF="https://example.com/docs/?utm_source=x" ADD_DATE="1">Example</A>
</DL><p></DL><p></DL><p>'''

def test_normalize_url_removes_tracking_and_trailing_slash():
    assert normalize_url("https://EXAMPLE.com/docs/?utm_source=x") == "https://example.com/docs"

def test_parse_render_parse_preserves_path_and_attributes():
    first = parse_html(SAMPLE)
    second = parse_html(render_html(first))
    assert second.bookmarks()[0].path == ("02_AI 与智能开发",)
    assert second.bookmarks()[0].attrs["add_date"] == "1"
```

- [ ] **Step 2: Run the focused tests and verify the missing module failure**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_bookmark_domain.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.bookmark_domain'`.

- [ ] **Step 3: Add project metadata and the minimal domain adapter**

```python
@dataclass(frozen=True)
class BookmarkRecord:
    title: str
    url: str
    path: tuple[str, ...]
    attrs: dict[str, str]

def normalize_url(url: str) -> str:
    return organizer_normalize_url(url)

def parse_html(content: str) -> BookmarkTree:
    parser = NetscapeBookmarkParser()
    parser.feed(content)
    return BookmarkTree.from_legacy_root(parser.root)

def render_html(tree: BookmarkTree) -> str:
    return render_netscape_tree(tree)
```

Copy the existing algorithms into focused functions rather than importing the CLI scripts at runtime. Preserve their behavior and add no network metadata fetching.

- [ ] **Step 4: Run domain tests and the existing audit on the real file**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_bookmark_domain.py -v`

Expected: PASS.

Run: `python3 '30-资源/工具/书签管理/bookmark_audit.py' "$NAV_PRIVATE_BOOKMARK_FIXTURE" --policy '30-资源/工具/书签管理/bookmark_policy.json' -o /tmp/navigation-baseline-audit.md --json /tmp/navigation-baseline-audit.json`

Expected: exit 0 and JSON reports `duplicate_url_count: 0`.

- [ ] **Step 5: Commit the isolated domain layer**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add bookmark domain layer'
```

---

### Task 2: Add SQLite persistence and initial migration

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/app/db.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/models.py`
- Create: `30-资源/工具/书签管理/navigation/backend/alembic.ini`
- Create: `30-资源/工具/书签管理/navigation/backend/alembic/env.py`
- Create: `30-资源/工具/书签管理/navigation/backend/alembic/versions/0001_initial.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_models.py`

**Interfaces:**
- Produces: `get_session() -> Iterator[Session]`
- Produces: `User`, `Folder`, `Bookmark`, `SessionToken`, `ImportBatch`, `ImportItem`, `Operation`, and `Backup` ORM models.
- Constraint: `Bookmark.normalized_url` is unique for active bookmarks.
- Constraint: `(Folder.parent_id, Folder.base_name)` and `(Folder.parent_id, Folder.position)` are unique.

- [ ] **Step 1: Write failing model tests for uniqueness and tree identity**

```python
def test_duplicate_normalized_url_is_rejected(session):
    session.add_all([
        Bookmark(title="A", url="https://x.test/", normalized_url="https://x.test", folder_id=1),
        Bookmark(title="B", url="https://x.test", normalized_url="https://x.test", folder_id=1),
    ])
    with pytest.raises(IntegrityError):
        session.commit()

def test_folder_renumbering_does_not_change_id(session):
    folder = Folder(base_name="Codex", position=2)
    session.add(folder); session.commit()
    stable_id = folder.id
    folder.position = 3; session.commit()
    assert folder.id == stable_id
```

- [ ] **Step 2: Run tests and verify model imports fail**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_models.py -v`

Expected: FAIL because `app.models` is absent.

- [ ] **Step 3: Implement models, SQLite pragmas, and migration**

```python
class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"))
    base_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("parent_id", "base_name"),
        UniqueConstraint("parent_id", "position"),
    )
```

Enable `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, and a 5-second busy timeout on connection. The migration must create every listed table, index bookmark title and normalized URL, and use UTC timestamps.

- [ ] **Step 4: Run migration and model tests**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && DATABASE_URL=sqlite:////tmp/navigation-test.db python3 -m alembic upgrade head`

Expected: exit 0 and revision `0001_initial` applied.

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit persistence**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add sqlite persistence'
```

---

### Task 3: Implement single-user authentication and application shell

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/app/main.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/security.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/dependencies.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/schemas.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/auth.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_auth.py`

**Interfaces:**
- Produces: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`.
- Produces: `require_user(request, session) -> User` and `require_csrf(request) -> None`.
- Produces: CLI command `python -m app.main create-user --username NAME` reading the password from a prompt or `NAV_INITIAL_PASSWORD_FILE`.

- [ ] **Step 1: Write failing authentication tests**

```python
def test_bookmark_content_requires_login(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401

def test_login_sets_secure_cookie_and_csrf(client, user):
    response = client.post("/api/v1/auth/login", json={"username": "yong", "password": "correct horse"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.json()["csrf_token"]

def test_repeated_failures_are_rate_limited(client, user):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "yong", "password": "wrong"})
    assert client.post("/api/v1/auth/login", json={"username": "yong", "password": "wrong"}).status_code == 429
```

- [ ] **Step 2: Run tests and verify authentication endpoints are missing**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_auth.py -v`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement Argon2 passwords, opaque sessions, CSRF, and throttling**

```python
password_hash = PasswordHash.recommended()

def new_session_tokens() -> tuple[str, str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest, csrf

def require_csrf(request: Request, token: SessionToken = Depends(require_session)) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, token.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
```

Store only the session-token digest, expire sessions after the configured lifetime, set `Secure` outside test mode, and key an in-memory bounded failure window by normalized username plus trusted client IP.

- [ ] **Step 4: Run auth tests and verify no password appears in the database**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_auth.py -v`

Expected: PASS and the test database contains an Argon2 hash beginning with `$argon2`.

- [ ] **Step 5: Commit authentication**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add secure single-user auth'
```

---

### Task 4: Implement folder, bookmark, and search APIs

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/app/bookmark_service.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/folders.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/bookmarks.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_bookmark_api.py`

**Interfaces:**
- Produces: `GET/POST/PATCH/DELETE /api/v1/folders` and `/api/v1/folders/{id}`.
- Produces: `GET/POST/PATCH/DELETE /api/v1/bookmarks` and `/api/v1/bookmarks/{id}`.
- Produces: `GET /api/v1/search?q=&folder_id=&limit=&offset=`.
- Produces: `renumber_siblings(session: Session, parent_id: int | None) -> None`.

- [ ] **Step 1: Write failing CRUD, cycle, duplicate, and search tests**

```python
def test_moving_folder_below_descendant_is_rejected(auth_client, tree):
    response = auth_client.patch(f"/api/v1/folders/{tree.root_id}", json={"parent_id": tree.child_id})
    assert response.status_code == 409

def test_duplicate_url_returns_existing_bookmark(auth_client, folder):
    auth_client.post("/api/v1/bookmarks", json={"title": "A", "url": "https://x.test/?utm_source=a", "folder_id": folder.id})
    response = auth_client.post("/api/v1/bookmarks", json={"title": "B", "url": "https://x.test", "folder_id": folder.id})
    assert response.status_code == 409
    assert response.json()["existing_id"]

def test_search_matches_title_url_folder_and_notes(auth_client, bookmark):
    response = auth_client.get("/api/v1/search", params={"q": "抓包"})
    assert response.json()["total"] == 1
```

- [ ] **Step 2: Run API tests and verify route failures**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_bookmark_api.py -v`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement transactional services and authenticated routers**

```python
def renumber_siblings(session: Session, parent_id: int | None) -> None:
    siblings = session.scalars(
        select(Folder).where(Folder.parent_id.is_(parent_id) if parent_id is None else Folder.parent_id == parent_id)
        .order_by(Folder.position, Folder.id)
    ).all()
    for position, folder in enumerate(siblings, 1):
        folder.position = position

def create_bookmark(session: Session, data: BookmarkCreate) -> Bookmark:
    normalized = normalize_url(data.url)
    existing = session.scalar(select(Bookmark).where(Bookmark.normalized_url == normalized))
    if existing:
        raise DuplicateBookmark(existing.id)
    bookmark = Bookmark(**data.model_dump(), normalized_url=normalized)
    session.add(bookmark)
    return bookmark
```

Search with escaped `LIKE` predicates over title, URL, notes, folder base name, and computed domain. All writes require CSRF and produce an `Operation` summary.

- [ ] **Step 4: Run focused and complete backend tests**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_bookmark_api.py -v`

Expected: PASS.

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit management APIs**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add tree management and search'
```

---

### Task 5: Implement preview-first HTML import and conflict resolution

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/app/import_service.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/backup_service.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/imports.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_imports.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_real_v5_import.py`
- Use: `30-资源/工具/书签管理/bookmark_policy.json`

**Interfaces:**
- Produces: `POST /api/v1/imports/preview` accepting one bounded HTML upload.
- Produces: `GET /api/v1/imports/{batch_id}`.
- Produces: `POST /api/v1/imports/{batch_id}/apply` with explicit per-field conflict choices.
- Produces: `ImportPreview(new, duplicate, conflict, suggested_move, unclassified)`.
- Produces: `create_backup(session: Session, reason: str) -> Backup`, the minimal atomic SQLite snapshot required before import mutation.

- [ ] **Step 1: Write failing preview and apply tests**

```python
def test_preview_does_not_mutate_and_missing_urls_do_not_delete(auth_client, seeded_db, import_html):
    before = seeded_db.bookmark_count()
    preview = auth_client.post("/api/v1/imports/preview", files={"file": ("bookmarks.html", import_html, "text/html")})
    assert preview.status_code == 200
    assert seeded_db.bookmark_count() == before
    assert "delete" not in preview.json()["summary"]

def test_existing_url_keeps_server_fields_by_default(auth_client, conflicting_batch, seeded_bookmark):
    auth_client.post(f"/api/v1/imports/{conflicting_batch.id}/apply", json={"overrides": []})
    seeded_bookmark.refresh()
    assert seeded_bookmark.title == "Server title"
    assert seeded_bookmark.notes == "Server notes"

def test_unclassified_new_url_goes_to_inbox(auth_client, unknown_html):
    batch = preview_and_apply(auth_client, unknown_html)
    assert batch.created[0].folder_path == ("00_待整理",)

def test_real_v5_import_has_expected_baseline(auth_client, project_root):
    content = Path(os.environ["NAV_PRIVATE_BOOKMARK_FIXTURE"]).read_bytes()
    preview = auth_client.post("/api/v1/imports/preview", files={"file": ("v5.html", content, "text/html")})
    result = auth_client.post(f"/api/v1/imports/{preview.json()['id']}/apply", json={"overrides": []})
    assert result.json()["unique_bookmarks"] == 665
    assert result.json()["duplicate_urls"] == 0
    assert result.json()["unclassified"] == 0
```

- [ ] **Step 2: Run import tests and verify routes are missing**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_imports.py -v`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement immutable preview batches and transactional apply**

```python
class ConflictChoice(BaseModel):
    item_id: int
    overwrite_title: bool = False
    overwrite_folder: bool = False

def apply_batch(session: Session, batch: ImportBatch, choices: list[ConflictChoice]) -> ApplyResult:
    if batch.status != "previewed":
        raise ImportStateError(batch.status)
    backup = create_backup(session, reason=f"before-import:{batch.id}")
    with session.begin_nested():
        result = merge_preview_items(session, batch.items, choices)
        renumber_all_folders(session)
        assert_tree_is_valid(session)
        batch.status = "applied"
        batch.backup_id = backup.id
    return result
```

Reject files over the configured byte limit, reject non-HTML content, expire unapplied batches, and store parsed preview data rather than the original filename. Classification reads the mounted policy path. Implement the atomic SQLite snapshot and checksum portion of `backup_service.py` here so import apply never depends on a later task.

- [ ] **Step 4: Run import tests plus the real V5 import acceptance test**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_imports.py -v`

Expected: PASS.

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_real_v5_import.py -v`

Expected: PASS with exactly 665 unique bookmarks, 0 duplicates, and 0 unclassified items for the baseline V5 file.

- [ ] **Step 5: Commit safe importing**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add preview-first html import'
```

---

### Task 6: Add export, backup, restore, and retention

**Files:**
- Create: `30-资源/工具/书签管理/navigation/backend/app/export_service.py`
- Modify: `30-资源/工具/书签管理/navigation/backend/app/backup_service.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/exports.py`
- Create: `30-资源/工具/书签管理/navigation/backend/app/routers/backups.py`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_export_backup.py`

**Interfaces:**
- Produces: `GET /api/v1/exports/bookmarks.html` and `GET /api/v1/exports/backup.json`.
- Produces: `GET /api/v1/backups`, `POST /api/v1/backups/{id}/restore`.
- Consumes: `create_backup(session, reason: str) -> Backup` from Task 5.
- Produces: restore, checksum verification, and `prune_backups(now: datetime) -> PruneResult`.

- [ ] **Step 1: Write failing round-trip, authorization, and restore tests**

```python
def test_html_export_round_trip_preserves_urls_paths_and_attrs(auth_client, imported_v5):
    exported = auth_client.get("/api/v1/exports/bookmarks.html")
    assert exported.status_code == 200
    tree = parse_html(exported.text)
    assert len(tree.bookmarks()) == 665
    assert set(tree.normalized_urls()) == set(imported_v5.normalized_urls())
    assert set(tree.paths()) == set(imported_v5.paths())

def test_restore_creates_pre_restore_backup(auth_client, backup, operation_count):
    response = auth_client.post(f"/api/v1/backups/{backup.id}/restore")
    assert response.status_code == 200
    assert response.json()["pre_restore_backup_id"] != backup.id

def test_recursive_folder_delete_creates_backup(auth_client, populated_folder):
    response = auth_client.delete(
        f"/api/v1/folders/{populated_folder.id}?recursive=true",
        headers={"X-Confirm-Delete": populated_folder.base_name},
    )
    assert response.status_code == 200
    assert response.json()["backup_id"]
```

- [ ] **Step 2: Run tests and verify export/backup routes fail**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_export_backup.py -v`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement audited exports and atomic SQLite snapshots**

```python
def create_backup(session: Session, reason: str) -> Backup:
    destination = settings.backup_dir / f"{utc_stamp()}-{safe_reason(reason)}.sqlite3"
    source = session.connection().connection.driver_connection
    with sqlite3.connect(destination) as target:
        source.backup(target)
    digest = sha256_file(destination)
    backup = Backup(path=str(destination), sha256=digest, reason=reason)
    session.add(backup)
    return backup

def export_bookmarks_html(session: Session) -> str:
    tree = build_numbered_tree(session)
    errors = audit_tree(tree)
    if errors.blocking:
        raise ExportAuditError(errors)
    return render_html(tree)
```

Verify checksums before restore, restore through a temporary file plus atomic replacement, and retain the newest 30 operation backups plus one daily backup for 30 days by default.
Extend recursive folder deletion here: it must require the exact folder name in `X-Confirm-Delete`, create a backup, and delete the subtree in one transaction. Task 4 may only delete empty folders.

- [ ] **Step 4: Run tests and compare exported V5 with the baseline audit**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_export_backup.py tests/test_real_v5_import.py -v`

Expected: PASS and the exported round-trip has 665 bookmarks, zero duplicate normalized URLs, and continuous folder numbering.

- [ ] **Step 5: Commit portability and recovery**

```bash
git add '30-资源/工具/书签管理/navigation/backend'
git commit -m 'feat(bookmarks): add export and recovery'
```

---

### Task 7: Build the authenticated Vue workspace

**Files:**
- Create: `30-资源/工具/书签管理/navigation/frontend/package.json`
- Create: `30-资源/工具/书签管理/navigation/frontend/vite.config.ts`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/main.ts`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/api.ts`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/router.ts`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/stores/bookmarks.ts`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/views/LoginView.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/views/WorkspaceView.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/AppToolbar.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/FolderTree.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/BookmarkList.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/BookmarkEditor.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/tests/workspace.spec.ts`

**Interfaces:**
- Consumes: auth, folder, bookmark, and search endpoints from Tasks 3–4.
- Produces: responsive login and three-column workspace with mobile drawer.
- Produces: debounced global search, keyboard result navigation, list/card toggle, and CRUD editor.

- [ ] **Step 1: Write failing store and workspace tests**

```typescript
it('debounces search and opens the selected result', async () => {
  const wrapper = mount(WorkspaceView, { global: testPlugins() })
  await wrapper.get('[data-test="global-search"]').setValue('wireshark')
  await vi.advanceTimersByTimeAsync(250)
  expect(api.search).toHaveBeenCalledWith({ q: 'wireshark', limit: 50, offset: 0 })
  await wrapper.get('[data-test="result-0"]').trigger('click')
  expect(window.open).toHaveBeenCalledWith('https://www.wireshark.org/', '_blank', 'noopener')
})

it('collapses the folder tree into a drawer on narrow screens', async () => {
  setViewport(390, 844)
  const wrapper = mount(WorkspaceView, { global: testPlugins() })
  expect(wrapper.get('[data-test="folder-drawer"]').attributes('aria-hidden')).toBe('true')
})
```

- [ ] **Step 2: Install locked dependencies and verify tests fail**

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm install`

Expected: exit 0 and `package-lock.json` created.

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm test -- --run`

Expected: FAIL because workspace components are missing.

- [ ] **Step 3: Implement login, API client, store, and responsive workspace**

```typescript
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD'].includes(init.method ?? 'GET') && csrfToken.value) {
    headers.set('X-CSRF-Token', csrfToken.value)
  }
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: 'same-origin' })
  if (response.status === 401) router.push('/login')
  if (!response.ok) throw await ApiError.fromResponse(response)
  return response.json() as Promise<T>
}
```

Use semantic buttons, visible focus states, labeled forms, `aria-expanded` on tree nodes, and CSS grid columns `minmax(240px, 20vw) minmax(360px, 1fr) minmax(280px, 24vw)`. Below 800px, show only the center column and place the folder tree and editor in accessible overlays.

- [ ] **Step 4: Run unit tests, type checks, and production build**

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm test -- --run && npm run typecheck && npm run build`

Expected: all tests pass, typecheck exits 0, and `dist/` is generated.

- [ ] **Step 5: Commit the workspace UI**

```bash
git add '30-资源/工具/书签管理/navigation/frontend'
git commit -m 'feat(bookmarks): add responsive navigation workspace'
```

---

### Task 8: Build import, export, backup, and destructive-action UI

**Files:**
- Create: `30-资源/工具/书签管理/navigation/frontend/src/views/ImportView.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/ImportSummary.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/ConflictTable.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/components/ConfirmDialog.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/src/views/BackupView.vue`
- Create: `30-资源/工具/书签管理/navigation/frontend/tests/import-export.spec.ts`

**Interfaces:**
- Consumes: import/export/backup endpoints from Tasks 5–6.
- Produces: upload-preview-confirm flow with explicit overwrite choices.
- Produces: HTML/JSON download actions, backup list, restore confirmation, and browser append-warning copy.

- [ ] **Step 1: Write failing import safety tests**

```typescript
it('does not enable apply until preview is loaded', async () => {
  const wrapper = mount(ImportView, { global: testPlugins() })
  expect(wrapper.get('[data-test="apply-import"]').attributes()).toHaveProperty('disabled')
  await uploadFixture(wrapper, 'bookmarks.html')
  await flushPromises()
  expect(wrapper.get('[data-test="new-count"]').text()).toContain('12')
  expect(wrapper.get('[data-test="apply-import"]').attributes()).not.toHaveProperty('disabled')
})

it('defaults all conflict overwrite controls to off', async () => {
  const wrapper = await mountConflictPreview()
  expect(wrapper.findAll('[data-test="overwrite-title"]:checked')).toHaveLength(0)
  expect(wrapper.text()).toContain('不会根据导入文件缺失项删除服务器书签')
})
```

- [ ] **Step 2: Run tests and verify missing component failures**

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm test -- --run tests/import-export.spec.ts`

Expected: FAIL because `ImportView.vue` is absent.

- [ ] **Step 3: Implement preview tables and guarded operations**

```typescript
const choices = computed(() => conflicts.value.map(item => ({
  item_id: item.id,
  overwrite_title: item.overwriteTitle,
  overwrite_folder: item.overwriteFolder,
})))

async function applyImport() {
  if (!batch.value || applying.value) return
  applying.value = true
  try {
    result.value = await imports.apply(batch.value.id, { overrides: choices.value })
  } finally {
    applying.value = false
  }
}
```

Require typed confirmation for recursive folder deletion and backup restore. Export links must use authenticated fetch-to-Blob so API errors cannot be mistaken for downloaded HTML.

- [ ] **Step 4: Run frontend tests and build**

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm test -- --run && npm run typecheck && npm run build`

Expected: all tests and type checks pass.

- [ ] **Step 5: Commit data-management UI**

```bash
git add '30-资源/工具/书签管理/navigation/frontend'
git commit -m 'feat(bookmarks): add safe import and recovery ui'
```

---

### Task 9: Package, document, and verify the complete deployment

**Files:**
- Create: `30-资源/工具/书签管理/navigation/Dockerfile`
- Create: `30-资源/工具/书签管理/navigation/compose.yaml`
- Create: `30-资源/工具/书签管理/navigation/.dockerignore`
- Create: `30-资源/工具/书签管理/navigation/.env.example`
- Create: `30-资源/工具/书签管理/navigation/README.md`
- Create: `30-资源/工具/书签管理/navigation/deploy/nginx.conf.example`
- Create: `30-资源/工具/书签管理/navigation/backend/tests/test_health.py`
- Create: `30-资源/工具/书签管理/navigation/frontend/e2e/navigation.spec.ts`

**Interfaces:**
- Produces: `GET /healthz` without bookmark data and authenticated SPA fallback.
- Produces: one `bookmark-navigation` Compose service bound to `127.0.0.1` by default.
- Produces: documented initialization, HTTPS proxying, backup, upgrade, rollback, import, and export procedures.

- [ ] **Step 1: Write failing health and end-to-end acceptance tests**

```python
def test_health_does_not_require_auth_or_leak_data(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

```typescript
test('login, search, edit, export, and logout', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('yong')
  await page.getByLabel('密码').fill('test-password')
  await page.getByRole('button', { name: '登录' }).click()
  await page.getByPlaceholder('搜索标题、网址、目录或备注').fill('Wireshark')
  await expect(page.getByText('Wireshark - 抓包分析')).toBeVisible()
  await page.getByRole('button', { name: '导出' }).click()
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page).toHaveURL(/\/login$/)
})
```

- [ ] **Step 2: Run health test and verify the route is missing**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest tests/test_health.py -v`

Expected: FAIL with 404.

- [ ] **Step 3: Add multi-stage image, Compose service, health check, and operations guide**

```dockerfile
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --create-home app
WORKDIR /app
COPY backend/ ./
RUN pip install --no-cache-dir .
COPY --from=frontend /src/dist /app/static
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

```yaml
services:
  bookmark-navigation:
    build: .
    restart: unless-stopped
    env_file: .env
    ports: ["127.0.0.1:8080:8080"]
    volumes:
      - ${NAV_DATA_DIR:-./data}:/data
      - ../bookmark_policy.json:/config/bookmark_policy.json:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Document exact `.env` keys, user initialization, reverse-proxy security headers, volume backup, image upgrade, database migration, rollback, and manual browser import/export warnings.

- [ ] **Step 4: Run complete verification from a clean Compose build**

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest -q`

Expected: all backend tests pass.

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm test -- --run && npm run typecheck && npm run build`

Expected: all frontend checks pass.

Run: `cd '30-资源/工具/书签管理/navigation' && docker compose config && docker compose build && docker compose up -d --wait`

Expected: config and build exit 0; service becomes healthy.

Run: `cd '30-资源/工具/书签管理/navigation/frontend' && npm run test:e2e`

Expected: Playwright acceptance test passes against the Compose service.

Run: `cd '30-资源/工具/书签管理/navigation' && docker compose down`

Expected: containers stop cleanly while `data/` remains.

- [ ] **Step 5: Commit deployment and documentation**

```bash
git add '30-资源/工具/书签管理/navigation'
git commit -m 'feat(bookmarks): package private navigation service'
```

---

### Task 10: Final real-data acceptance and handoff

**Files:**
- Modify: `30-资源/工具/书签管理/navigation/README.md`
- Create: `30-资源/工具/书签管理/navigation/docs/acceptance-2026-07-13.md`

**Interfaces:**
- Consumes: complete application from Tasks 1–9 and the real V5 bookmark HTML.
- Produces: reproducible acceptance evidence and deployment handoff.

- [ ] **Step 1: Start a clean acceptance instance and import the real V5 file**

Run: `cd '30-资源/工具/书签管理/navigation' && NAV_DATA_DIR=/tmp/bookmark-navigation-acceptance docker compose up -d --build --wait`

Expected: service healthy with a newly initialized database.

Use the authenticated import API or UI to preview and apply the repository-external file selected by `NAV_PRIVATE_BOOKMARK_FIXTURE`.

Expected preview/apply result: 665 unique bookmarks, 0 duplicate normalized URLs, all expected top-level folders, and no unexpected `00_待整理` entries.

- [ ] **Step 2: Export, reparse, and audit the accepted dataset**

Run: `python3 ../bookmark_audit.py /tmp/navigation-export.html --policy ../bookmark_policy.json -o /tmp/navigation-final-audit.md --json /tmp/navigation-final-audit.json`

Expected: exit 0 with duplicate URL, generic folder, oversized folder, empty-folder anomaly, and numbering anomaly counts all zero.

- [ ] **Step 3: Record exact evidence and operational caveats**

```markdown
# Acceptance Evidence — 2026-07-13

- Source file: repository-external private fixture
- Imported unique bookmarks: 665
- Exported unique bookmarks: 665
- Duplicate normalized URLs: 0
- Unexpected inbox bookmarks: 0
- Folder numbering anomalies: 0
- Authentication checks: unauthenticated API and export requests return 401
- Recovery check: restore created a pre-restore backup and restored the expected count
```

Add the actual command output and any deviation; do not claim a zero count unless the generated reports prove it.

- [ ] **Step 4: Run final clean-worktree-aware verification**

Run: `git status --short`

Expected: only the known unrelated `.obsidian/app.json` modification plus the acceptance documentation before commit.

Run: `cd '30-资源/工具/书签管理/navigation/backend' && python3 -m pytest -q && cd ../frontend && npm test -- --run && npm run typecheck && npm run build`

Expected: every command exits 0.

- [ ] **Step 5: Commit acceptance evidence**

```bash
git add '30-资源/工具/书签管理/navigation/README.md' '30-资源/工具/书签管理/navigation/docs/acceptance-2026-07-13.md'
git commit -m 'docs(bookmarks): record navigation acceptance'
```
