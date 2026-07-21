import os
import json
import re
import shlex
import subprocess
import tomllib
from pathlib import Path


NAVIGATION_ROOT = Path(__file__).parents[2]
BOOKMARK_ROOT = NAVIGATION_ROOT.parent
OPS_HELPER = NAVIGATION_ROOT / "deploy/navigation-ops.sh"


def test_backend_package_discovery_only_includes_the_application():
    config = tomllib.loads((NAVIGATION_ROOT / "backend/pyproject.toml").read_text())

    assert config["tool"]["setuptools"]["packages"]["find"]["include"] == ["app*"]


def test_docker_build_context_excludes_local_dependency_and_build_artifacts():
    dockerignore = (NAVIGATION_ROOT / ".dockerignore").read_text().splitlines()

    for generated_path in (
        "backend/.venv",
        "backend/venv",
        "backend/.pytest_cache",
        "frontend/node_modules",
        "frontend/dist",
    ):
        assert generated_path in dockerignore


def _bash_block_containing(readme: str, command: str) -> str:
    return next(
        block
        for block in re.findall(r"```bash\n(.*?)```", readme, flags=re.DOTALL)
        if command in block
    )


def test_initialization_prepares_non_root_bind_mount_and_password_file():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    helper = OPS_HELPER.read_text()
    env_example = (NAVIGATION_ROOT / ".env.example").read_text()

    assert "resolve_data_dir" in readme
    assert "docker compose config --format json" in helper
    assert 'sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR"' in readme
    assert 'PASSWORD_FILE="$DATA_DIR/.navigation-initial-password"' in readme
    assert 'sudo chown 10001:10001 "$PASSWORD_FILE"' in readme
    assert 'sudo chmod 600 "$PASSWORD_FILE"' in readme
    assert 'sudo shred --remove "$PASSWORD_FILE"' in readme
    assert "NAV_INITIAL_PASSWORD_FILE=/data/.navigation-initial-password" in env_example
    assert "/tmp/navigation-initial-password" not in readme


def test_operational_helper_is_committed_and_defines_all_guards():
    helper = OPS_HELPER.read_text()

    assert helper.startswith("#!/usr/bin/env bash")
    for function in (
        "resolve_data_dir",
        "resolve_nav_port",
        "require_data_marker",
        "require_outside_data_tree",
    ):
        assert f"{function}()" in helper


def test_every_standalone_operational_block_sources_helper_before_guard_or_action():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    first_commands = (
        "cp .env.example .env",
        'DATA_DIR="$(resolve_data_dir)"',
        "docker compose build",
        'BACKUP_FILE="$(require_outside_data_tree',
        "RESTORE_ARCHIVE=./navigation-data-",
        "docker compose build --pull",
        "docker compose up -d --wait --no-build",
        "docker compose ps",
    )

    for command in first_commands:
        block = _bash_block_containing(readme, command)
        fail_fast = block.index("set -euo pipefail")
        source = block.index("source ./deploy/navigation-ops.sh")
        action = block.index(command)
        assert fail_fast < source < action

    initialization = _bash_block_containing(readme, "docker compose build")
    assert initialization.index('require_data_marker "$DATA_DIR"') < initialization.index(
        "docker compose build"
    )


def test_missing_helper_or_failed_marker_stops_before_action(tmp_path):
    action = tmp_path / "action-ran"
    missing_helper = tmp_path / "missing-navigation-ops.sh"
    missing_result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "\n".join(
                (
                    "set -euo pipefail",
                    f"source {shlex.quote(str(missing_helper))}",
                    f"touch {shlex.quote(str(action))}",
                )
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert missing_result.returncode != 0
    assert not action.exists()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n")
    fake_sudo.chmod(0o755)
    unmarked_data = tmp_path / "data"
    unmarked_data.mkdir()
    env = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
    marker_result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "\n".join(
                (
                    "set -euo pipefail",
                    f"source {shlex.quote(str(OPS_HELPER))}",
                    f"require_data_marker {shlex.quote(str(unmarked_data))}",
                    f"touch {shlex.quote(str(action))}",
                )
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert marker_result.returncode != 0
    assert "refusing unmarked DATA_DIR" in marker_result.stderr
    assert not action.exists()


def test_data_directory_is_dedicated_and_marked_before_recursive_chown():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    helper = OPS_HELPER.read_text()
    initialization = readme.split("## 首次初始化", 1)[1].split(
        "## HTTPS 反向代理", 1
    )[0]

    assert 'pathlib.Path.cwd().resolve()' in helper
    assert 'pathlib.Path("/home")' in helper
    assert 'pathlib.Path("/var/lib")' in helper
    empty_guard = initialization.index(
        'sudo find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit'
    )
    marker = initialization.index("printf 'private-bookmark-navigation-data-v1")
    recursive_chown = initialization.index('sudo chown -R 10001:10001 "$DATA_DIR"')
    assert empty_guard < marker < recursive_chown
    assert "refusing non-empty unmarked DATA_DIR" in initialization


def test_operations_resolve_compose_data_dir_and_published_port():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    helper = OPS_HELPER.read_text()

    assert "resolve_nav_port" in readme
    assert 'NAV_PORT="$(resolve_nav_port)"' in readme
    assert 'curl --fail "http://127.0.0.1:${NAV_PORT}/healthz"' in readme
    assert 'DATA_DIR="$(resolve_data_dir)"' in readme
    assert 'tar -C "$DATA_DIR"' in readme
    assert '${NAV_DATA_DIR:-./data}' not in readme
    assert readme.count("set -euo pipefail") >= 3
    assert "backup output must be outside DATA_DIR" in helper
    assert readme.count("trap 'docker compose start bookmark-navigation'") == 1
    assert "恢复任一步骤失败时保持停服" in readme


def test_backup_and_restore_require_marker_before_recursive_actions():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    operations = readme.split("## 备份与恢复", 1)[1].split(
        "## 升级和数据库迁移", 1
    )[0]
    backup, restore = operations.split("恢复完整卷时", 1)

    assert backup.index('require_data_marker "$DATA_DIR"') < backup.index(
        'sudo tar -C "$DATA_DIR"'
    )
    marker_guard = restore.index('require_data_marker "$DATA_DIR"')
    stop = restore.index("docker compose stop bookmark-navigation")
    recursive_rm = restore.index('sudo find "$DATA_DIR"')
    assert marker_guard < stop < recursive_rm
    assert 'mktemp --tmpdir="${TMPDIR:-/tmp}"' in restore
    pre_restore_guard = restore.index(
        'require_outside_data_tree "$DATA_DIR" "$PRE_RESTORE"'
    )
    restore_archive_guard = restore.index(
        'require_outside_data_tree "$DATA_DIR" "$RESTORE_ARCHIVE"'
    )
    assert restore_archive_guard < pre_restore_guard < stop < recursive_rm
    recreated_marker = restore.index(
        "printf 'private-bookmark-navigation-data-v1", recursive_rm
    )
    recursive_chown = restore.index('sudo chown -R 10001:10001 "$DATA_DIR"')
    assert recursive_rm < recreated_marker < recursive_chown


def test_password_cleanup_trap_precedes_file_creation():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    initialization = readme.split("## 首次初始化", 1)[1].split(
        "## HTTPS 反向代理", 1
    )[0]

    trap = initialization.index("trap cleanup_password EXIT HUP INT TERM")
    creation = initialization.index('sudo tee "$PASSWORD_FILE"')
    assert "cleanup_password()" in initialization
    assert trap < creation


def test_restore_documentation_allows_canonicalized_relative_archive_paths():
    readme = (NAVIGATION_ROOT / "README.md").read_text()

    assert "归档路径可以是绝对路径或现有的相对路径" in readme
    assert 'RESTORE_ARCHIVE="$(readlink -f -- "$RESTORE_ARCHIVE")"' in readme
    assert "拒绝根目录、相对归档" not in readme


def test_marker_guard_precedes_upgrade_rollback_and_routine_operations():
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    upgrade = readme.split("## 升级和数据库迁移", 1)[1].split("## 回滚", 1)[0]
    rollback = readme.split("## 回滚", 1)[1].split("## 手动导入与导出", 1)[0]
    operations = readme.split("## 运维检查", 1)[1]

    assert upgrade.index('require_data_marker "$DATA_DIR"') < upgrade.index(
        "docker compose build --pull"
    )
    assert rollback.index('require_data_marker "$DATA_DIR"') < rollback.index(
        "docker compose up -d --wait --no-build"
    )
    assert operations.index('require_data_marker "$DATA_DIR"') < operations.index(
        "docker compose ps"
    )


def test_e2e_name_describes_the_actions_it_performs():
    acceptance = (NAVIGATION_ROOT / "frontend/e2e/navigation.spec.ts").read_text()

    assert "independent columns and persistent expand controls" in acceptance
    assert "ordinary user sees only their isolated bookmark" in acceptance
    assert "login, search, edit, export, and logout" not in acceptance


def test_forwarded_headers_use_an_explicit_proxy_allowlist():
    dockerfile = (NAVIGATION_ROOT / "Dockerfile").read_text()
    nginx = (NAVIGATION_ROOT / "deploy/nginx.conf.example").read_text()
    env_example = (NAVIGATION_ROOT / ".env.example").read_text()
    readme = (NAVIGATION_ROOT / "README.md").read_text()

    assert 'FORWARDED_ALLOW_IPS=${NAV_TRUSTED_PROXY_IPS:-172.30.0.1}' in dockerfile
    assert '--forwarded-allow-ips", "*"' not in dockerfile
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx
    compose = json.loads(subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(NAVIGATION_ROOT / "compose.yaml")],
        check=True, capture_output=True, text=True,
    ).stdout)
    bridge = compose["networks"]["navigation"]
    config = bridge["ipam"]["config"][0]
    service_network = compose["services"]["bookmark-navigation"]["networks"]["navigation"]
    assert config == {
        "subnet": "${NAV_DOCKER_SUBNET:-172.30.0.0/24}",
        "gateway": "${NAV_DOCKER_GATEWAY:-172.30.0.1}",
    }
    assert service_network["ipv4_address"] == "${NAV_APP_IP:-172.30.0.2}"
    assert "NAV_TRUSTED_PROXY_IPS=172.30.0.1" in env_example
    assert "NAV_DOCKER_SUBNET=172.30.0.0/24" in env_example
    assert "NAV_DOCKER_GATEWAY=172.30.0.1" in env_example
    assert "NAV_APP_IP=172.30.0.2" in env_example
    assert "Docker bridge" in readme
    assert "subnet conflict" in readme
    assert "NAV_DOCKER_GATEWAY" in readme
    assert "single Uvicorn worker" in readme


def test_readme_first_is_the_single_entry_and_explains_source_boundaries():
    entry = (BOOKMARK_ROOT / "README_FIRST.md").read_text()

    for scenario in ("直接使用", "新服务器部署", "日常整理", "开发维护"):
        assert scenario in entry
    for required_file in (
        "bookmark_policy.json",
        "BOOKMARK_RULES.md",
        "bookmark_organizer.py",
        "bookmark_numbering.py",
        "bookmark_audit.py",
        "navigation/",
    ):
        assert (BOOKMARK_ROOT / required_file).exists()
        assert required_file in entry
    for excluded_artifact in (
        "bookmark-navigation-offline-amd64-2026.07.15-r1.tar.gz",
    ):
        assert not (BOOKMARK_ROOT / excluded_artifact).exists()
        assert excluded_artifact in entry
    assert "NAV_PRIVATE_BOOKMARK_FIXTURE" in entry
    assert "私人验收样本" in entry
    assert "唯一主入口" in entry
    assert "不纳入当前独立源码目录" in entry
    assert "单独发布的二进制交付物" in entry
    assert "release/docs/DEPLOYMENT.md" in entry


def test_development_history_navigation_opens_real_index_documents():
    entry = (BOOKMARK_ROOT / "README_FIRST.md").read_text()
    indexes = (
        NAVIGATION_ROOT / "docs/superpowers/specs/README.md",
        NAVIGATION_ROOT / "docs/superpowers/plans/README.md",
    )

    assert "navigation/docs/superpowers/specs/README.md" in entry
    assert "navigation/docs/superpowers/plans/README.md" in entry

    for index in indexes:
        assert index.is_file()
        content = index.read_text()
        links = re.findall(r"\[[^]]+\]\(([^)]+\.md)\)", content)
        assert links
        for target in links:
            assert (index.parent / target).resolve().is_file(), target


def test_offline_build_example_uses_manifest_image_tag():
    manifest = dict(
        line.split("=", 1)
        for line in (NAVIGATION_ROOT / "release" / "MANIFEST").read_text().splitlines()
    )
    guide = (NAVIGATION_ROOT / "release" / "docs" / "DEPLOYMENT.md").read_text()

    assert f"--image {manifest['image_repository']}:{manifest['image_tag']}" in guide


def test_source_guide_explains_navigation_directory_responsibilities():
    source_guide = (NAVIGATION_ROOT / "README.md").read_text()

    assert "源码构建与高级运维" in source_guide
    assert "普通部署不应从本文开始" in source_guide
    for required_path in (
        "backend/",
        "frontend/",
        "Dockerfile",
        "compose.yaml",
        ".env.example",
        "deploy/",
        "release/",
        "docs/",
    ):
        assert required_path in source_guide


def test_offline_guide_explains_every_bundle_artifact():
    offline_guide = (NAVIGATION_ROOT / "release/docs/DEPLOYMENT.md").read_text()

    for artifact in (
        "install.sh",
        "compose.yaml",
        "image/bookmark-navigation-amd64.tar",
        "config/bookmark_policy.json",
        "VERSION",
        "MANIFEST",
        "SHA256SUMS",
        "docs/DEPLOYMENT.md",
    ):
        assert artifact in offline_guide
    assert "安装包文件作用" in offline_guide


def test_original_server_procedure_is_labeled_as_a_historical_record():
    record = (NAVIGATION_ROOT / "docs/linux-server-deployment-2026-07-14.md").read_text()

    assert "历史部署记录" in record
    assert "release/docs/DEPLOYMENT.md" in record


def test_public_release_metadata_and_content_are_sanitized():
    public_readme = (BOOKMARK_ROOT / "README.md").read_text()
    security = (BOOKMARK_ROOT / "SECURITY.md").read_text()
    license_text = (BOOKMARK_ROOT / "LICENSE").read_text()

    assert "README_FIRST.md" in public_readme
    assert "AGPL-3.0-only" in public_readme
    assert "安全" in security or "Security" in security
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text

    installer = (NAVIGATION_ROOT / "release/install.sh").read_text()
    offline_guide = (NAVIGATION_ROOT / "release/docs/DEPLOYMENT.md").read_text()
    assert 'USERNAME="admin"' in installer
    assert "Initial administrator username (default: admin)" in installer
    assert "默认管理员用户名为 `admin`" in offline_guide

    ignored_parts = {
        ".venv",
        "venv",
        "node_modules",
        "dist",
        ".pytest_cache",
        "__pycache__",
        ".git",
    }
    ignored_files = {Path(__file__).resolve()}
    text_suffixes = {
        ".html",
        ".json",
        ".md",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".vue",
        ".yaml",
        ".yml",
    }
    forbidden = (
        "wu" + "qi57",
        "long" + "yong.top",
        "id_ed25519_" + "ubuntu_vm",
        "bookmarks_personalized_" + "v5_2026_07_12.html",
        "/Users/" + "yong",
    )

    violations = []
    for path in BOOKMARK_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if ignored_parts.intersection(path.parts) or path.resolve() in ignored_files:
            continue
        content = path.read_text(errors="replace")
        for token in forbidden:
            if token in content:
                violations.append(f"{path.relative_to(BOOKMARK_ROOT)}: {token}")

    assert violations == []


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
        "bash navigation/release/build-offline-bundle.sh",
        "pull-requests: write",
        "contents: write",
    ):
        assert excluded not in workflow.lower()
