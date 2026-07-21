"""Minimal atomic SQLite snapshots used as import safety points."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Backup


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class PruneResult:
    kept: int
    deleted: int
    cleanup_failed: int = 0


def _connect_sqlite(path: Path) -> AbstractContextManager[sqlite3.Connection]:
    """Open a SQLite connection that is always closed on context exit."""

    return closing(sqlite3.connect(path))


def _database_path(session: Session) -> Path:
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        raise BackupError("Only SQLite backups are supported")
    database = bind.url.database
    if not database or database == ":memory:":
        raise BackupError("SQLite backup requires a file-backed database")
    return Path(database).expanduser().resolve()


def create_backup(session: Session, reason: str) -> Backup:
    """Create, fsync, checksum, and atomically publish a SQLite snapshot."""

    source_path = _database_path(session)
    backup_dir = Path(
        os.getenv("NAV_BACKUP_DIR", str(source_path.parent / "backups"))
    ).expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe_reason = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in reason
    )
    final_path = backup_dir / f"{stamp}-{safe_reason}-{uuid.uuid4().hex}.sqlite3"
    temporary_path = final_path.with_suffix(".tmp")
    published = False
    try:
        with _connect_sqlite(source_path) as source, _connect_sqlite(
            temporary_path
        ) as target:
            source.backup(target)
            target.commit()
        temporary_path.chmod(0o600)
        with temporary_path.open("rb") as snapshot:
            os.fsync(snapshot.fileno())
        checksum = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
        os.replace(temporary_path, final_path)
        published = True
        final_path.chmod(0o600)
        directory_fd = os.open(backup_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        if published:
            final_path.unlink(missing_ok=True)
        raise

    backup = Backup(path=str(final_path), checksum=checksum)
    try:
        session.add(backup)
        session.flush()
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    return backup


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_backups(session: Session) -> list[Backup]:
    return list(
        session.scalars(
            select(Backup).order_by(Backup.created_at.desc(), Backup.id.desc())
        ).all()
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def prune_backups(
    session: Session,
    now: datetime,
    *,
    operation_limit: int = 30,
    daily_days: int = 30,
) -> PruneResult:
    """Keep the newest operation snapshots and one snapshot per recent UTC day."""

    backups = list_backups(session)
    protected = [backup for backup in backups if backup.is_protected]
    ordinary = [backup for backup in backups if not backup.is_protected]
    keep_ids = {backup.id for backup in protected}
    keep_ids.update(backup.id for backup in ordinary[:operation_limit])
    cutoff = _naive_utc(now).date().toordinal() - daily_days + 1
    daily: set[int] = set()
    for backup in ordinary:
        day = _naive_utc(backup.created_at).date().toordinal()
        if day < cutoff or day in daily:
            continue
        daily.add(day)
        keep_ids.add(backup.id)

    removed = [backup for backup in backups if backup.id not in keep_ids]
    for backup in removed:
        session.delete(backup)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    referenced = {str(Path(backup.path).resolve()) for backup in backups if backup.id in keep_ids}
    backup_dirs = {Path(backup.path).parent for backup in backups}
    cleanup_failed = 0
    for backup_dir in backup_dirs:
        for snapshot in backup_dir.glob("*.sqlite3"):
            if str(snapshot.resolve()) in referenced:
                continue
            try:
                snapshot.unlink(missing_ok=True)
            except OSError:
                cleanup_failed += 1
    return PruneResult(
        kept=len(backups) - len(removed),
        deleted=len(removed),
        cleanup_failed=cleanup_failed,
    )


def enforce_backup_retention(session: Session) -> PruneResult | None:
    """Best-effort default retention after a backup-producing transaction commits."""

    try:
        return prune_backups(session, datetime.now(UTC))
    except Exception:
        session.rollback()
        return None


def _upgrade_snapshot(path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.attributes["navigation_restore_url"] = f"sqlite:///{path}"
    with _connect_sqlite(path) as database:
        has_version_table = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
        user_columns = {
            row[1] for row in database.execute("PRAGMA table_info(users)").fetchall()
        }
    if not has_version_table and {
        "is_admin",
        "is_active",
        "must_change_password",
    } <= user_columns:
        command.stamp(config, "head")
        return
    command.upgrade(config, "head")


def restore_backup(session: Session, backup: Backup, actor_username: str) -> int:
    """Verify and atomically restore a snapshot, retaining a pre-restore escape hatch."""

    source_path = Path(backup.path)
    if not source_path.is_file():
        raise BackupError("Backup file is missing")
    if sha256_file(source_path) != backup.checksum:
        raise BackupError("Backup checksum mismatch")

    try:
        with _connect_sqlite(source_path) as check:
            if check.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise BackupError("Backup database integrity check failed")
    except sqlite3.DatabaseError as error:
        raise BackupError("Backup database is invalid") from error

    database_path = _database_path(session)
    backup.is_protected = True
    pre_restore = create_backup(session, reason=f"pre-restore:{backup.id}")
    pre_restore.is_protected = True
    session.commit()
    pre_restore_path = Path(pre_restore.path)
    current_catalog = []
    for current in list_backups(session):
        path = Path(current.path)
        try:
            valid = path.is_file() and sha256_file(path) == current.checksum
        except OSError:
            valid = False
        if valid:
            current_catalog.append(
                {
                    "id": current.id,
                    "path": current.path,
                    "checksum": current.checksum,
                    "created_at": current.created_at.isoformat(sep=" "),
                    "is_protected": bool(current.is_protected),
                }
            )
    temporary_path = database_path.with_name(f".{database_path.name}.{uuid.uuid4().hex}.restore")
    engine = session.get_bind()
    try:
        with _connect_sqlite(source_path) as source, _connect_sqlite(
            temporary_path
        ) as target:
            source.backup(target)
            # The application re-enables WAL on its next connection. Publishing
            # a database that still names a temporary WAL sidecar can otherwise
            # produce a disk-I/O error after the first post-restore statement.
            target.execute("PRAGMA journal_mode=DELETE")
            target.commit()

        _upgrade_snapshot(temporary_path)
        with _connect_sqlite(temporary_path) as target:
            target.execute("PRAGMA journal_mode=DELETE")
            existing = {
                path: row_id
                for row_id, path in target.execute("SELECT id, path FROM backups")
            }
            used_ids = set(existing.values())
            merged_ids: dict[str, int] = {}
            for entry in current_catalog:
                if entry["path"] in existing:
                    merged_id = existing[entry["path"]]
                    target.execute(
                        "UPDATE backups SET checksum = ?, created_at = ?, "
                        "is_protected = ? WHERE id = ?",
                        (
                            entry["checksum"],
                            entry["created_at"],
                            entry["is_protected"],
                            merged_id,
                        ),
                    )
                elif entry["id"] not in used_ids:
                    target.execute(
                        "INSERT INTO backups "
                        "(id, path, checksum, is_protected, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            entry["id"],
                            entry["path"],
                            entry["checksum"],
                            entry["is_protected"],
                            entry["created_at"],
                        ),
                    )
                    merged_id = entry["id"]
                else:
                    cursor = target.execute(
                        "INSERT INTO backups "
                        "(path, checksum, is_protected, created_at) VALUES (?, ?, ?, ?)",
                        (
                            entry["path"],
                            entry["checksum"],
                            entry["is_protected"],
                            entry["created_at"],
                        ),
                    )
                    merged_id = int(cursor.lastrowid)
                used_ids.add(merged_id)
                merged_ids[entry["path"]] = merged_id
            pre_restore_id = merged_ids[str(pre_restore_path)]
            target.execute("DELETE FROM session_tokens")
            actor = target.execute(
                "SELECT id FROM users WHERE username = ?", (actor_username,)
            ).fetchone()
            actor_user_id = actor[0] if actor else None
            target.execute(
                "INSERT INTO admin_audits "
                "(actor_user_id, target_user_id, target_username, action, result) "
                "VALUES (?, ?, ?, 'backup.restore', 'success')",
                (actor_user_id, actor_user_id, actor_username),
            )
            target.commit()
            if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise BackupError("Restored database integrity check failed")
        temporary_path.chmod(0o600)
        with temporary_path.open("rb") as restored:
            os.fsync(restored.fileno())

        session.close()
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
        os.replace(temporary_path, database_path)
        directory_fd = os.open(database_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return pre_restore_id
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
