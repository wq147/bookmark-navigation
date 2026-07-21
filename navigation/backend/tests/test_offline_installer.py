from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


NAVIGATION_ROOT = Path(__file__).parents[2]
RELEASE_ROOT = NAVIGATION_ROOT / "release"
INSTALLER = RELEASE_ROOT / "install.sh"
BUILDER = RELEASE_ROOT / "build-offline-bundle.sh"


def _load_compose() -> dict:
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_file(ARGV[0]))",
            str(RELEASE_ROOT / "compose.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_release_tree_contains_runtime_only_artifacts():
    required = (
        "install.sh",
        "compose.yaml",
        "VERSION",
        "MANIFEST",
        "docs/DEPLOYMENT.md",
    )

    for relative_path in required:
        assert (RELEASE_ROOT / relative_path).is_file(), relative_path


def test_release_compose_uses_loaded_image_and_configurable_host_binding():
    compose = _load_compose()
    service = compose["services"]["bookmark-navigation"]

    assert "build" not in service
    assert service["image"] == "${NAV_IMAGE_REPOSITORY:-bookmark-navigation}:${NAV_IMAGE_TAG}"
    assert service["ports"] == ["${NAV_BIND_ADDRESS}:${NAV_PORT}:8080"]
    assert service["volumes"] == [
        "${NAV_DATA_DIR}:/data",
        "${NAV_POLICY_PATH}:/config/bookmark_policy.json:ro",
    ]
    assert service["networks"]["navigation"]["ipv4_address"] == "${NAV_APP_IP}"
    assert "healthcheck" in service

    network = compose["networks"]["navigation"]["ipam"]["config"][0]
    assert network == {
        "subnet": "${NAV_DOCKER_SUBNET}",
        "gateway": "${NAV_DOCKER_GATEWAY}",
    }


def test_installer_help_exposes_the_approved_interface():
    result = subprocess.run(
        ["bash", str(INSTALLER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    for option in (
        "--listen ADDRESS",
        "--port PORT",
        "--install-dir PATH",
        "--data-dir PATH",
        "--username USER",
        "--password-file FILE",
        "--yes",
        "--help",
    ):
        assert option in result.stdout


def test_release_metadata_declares_linux_amd64_and_image_archive():
    version = (RELEASE_ROOT / "VERSION").read_text().strip()
    manifest = (RELEASE_ROOT / "MANIFEST").read_text()

    assert version
    assert "platform=linux/amd64" in manifest
    assert "image_archive=image/bookmark-navigation-amd64.tar" in manifest


def _run_installer(*args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        env=os.environ | (env or {}),
    )


def test_invalid_port_is_rejected_before_system_mutation():
    for invalid in ("0", "65536", "abc", "80.5"):
        result = _run_installer("--port", invalid)
        assert result.returncode != 0
        assert "Invalid port" in result.stderr


def test_unknown_or_incomplete_options_are_rejected():
    unknown = _run_installer("--unknown")
    missing_value = _run_installer("--listen")

    assert unknown.returncode != 0
    assert "Unknown option" in unknown.stderr
    assert missing_value.returncode != 0
    assert "requires a value" in missing_value.stderr


def test_compose_unsafe_path_characters_are_rejected():
    for path in ("/tmp/bad:path", "/tmp/bad#path", "/tmp/bad path", "/tmp/bad\\path"):
        result = _run_installer("--install-dir", path)
        assert result.returncode != 0
        assert "Invalid install directory" in result.stderr


def test_installer_requires_root_before_loading_the_image():
    result = _run_installer(
        "--yes",
        env={"NAV_INSTALLER_TEST_EUID": "1000", "NAV_INSTALLER_TEST_MODE": "1"},
    )

    assert result.returncode != 0
    assert "must run as root" in result.stderr


def _make_fake_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    shutil.copytree(RELEASE_ROOT, bundle)
    (bundle / "image").mkdir()
    (bundle / "config").mkdir()
    (bundle / "image/bookmark-navigation-amd64.tar").write_text("fake image")
    (bundle / "config/bookmark_policy.json").write_text('{"version": 1}\n')

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docker %s\\n' \"$*\" >> \"$NAV_TEST_COMMAND_LOG\"\n"
        "case \"$*\" in\n"
        "  'info') exit 0 ;;\n"
        "  'compose version') echo 'Docker Compose version v2.30.0'; exit 0 ;;\n"
        "  'network ls --format {{.Name}}') exit 0 ;;\n"
        "  'network ls -q') if [ -n \"${NAV_TEST_NETWORK_ID:-}\" ]; then echo \"$NAV_TEST_NETWORK_ID\"; fi; exit 0 ;;\n"
        "  'network inspect '*) printf '%s\\n' \"${NAV_TEST_NETWORK_SUBNETS:-}\"; exit 0 ;;\n"
        "  'load -i '*) echo 'Loaded image: bookmark-navigation:2026-07-14-r2'; exit 0 ;;\n"
        "  'compose '*' ps --status running --services') echo bookmark-navigation; exit 0 ;;\n"
        "  'compose '*) exit 0 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    fake_docker.chmod(0o755)
    fake_ss = fake_bin / "ss"
    fake_ss.write_text(
        "#!/usr/bin/env bash\n"
        "if [ -n \"${NAV_TEST_SS_OUTPUT:-}\" ]; then printf '%s\\n' \"$NAV_TEST_SS_OUTPUT\"; fi\n"
    )
    fake_ss.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_curl.chmod(0o755)
    fake_chown = fake_bin / "chown"
    fake_chown.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'chown %s\\n' \"$*\" >> \"$NAV_TEST_COMMAND_LOG\"\n"
    )
    fake_chown.chmod(0o755)
    fake_realpath = fake_bin / "realpath"
    fake_realpath.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = -m ]; then shift; fi\n"
        "if [ \"${1:-}\" = -- ]; then shift; fi\n"
        "/usr/bin/python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' \"$1\"\n"
    )
    fake_realpath.chmod(0o755)
    fake_stat = fake_bin / "stat"
    fake_stat.write_text(
        "#!/usr/bin/env bash\n"
        "target=${!#}\n"
        "/usr/bin/python3 -c 'import os, stat, sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])' \"$target\"\n"
    )
    fake_stat.chmod(0o755)

    checksum_files = (
        "install.sh",
        "compose.yaml",
        "VERSION",
        "MANIFEST",
        "docs/DEPLOYMENT.md",
        "config/bookmark_policy.json",
        "image/bookmark-navigation-amd64.tar",
    )
    checksums = subprocess.run(
        ["shasum", "-a", "256", *checksum_files],
        cwd=bundle,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (bundle / "SHA256SUMS").write_text(checksums)
    return bundle, fake_bin


def test_preflight_rejects_wrong_platform_before_docker_load(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    result = subprocess.run(
        ["bash", str(bundle / "install.sh"), "--yes"],
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NAV_INSTALLER_TEST_MODE": "1",
            "NAV_INSTALLER_TEST_EUID": "0",
            "NAV_INSTALLER_TEST_OS": "Darwin",
            "NAV_INSTALLER_TEST_ARCH": "arm64",
            "NAV_TEST_COMMAND_LOG": str(tmp_path / "commands.log"),
        },
    )

    assert result.returncode != 0
    assert "requires Linux amd64" in result.stderr
    assert not (tmp_path / "commands.log").exists()


def test_checksum_failure_happens_before_docker_load(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    (bundle / "compose.yaml").write_text("tampered\n")
    log = tmp_path / "commands.log"
    result = subprocess.run(
        ["bash", str(bundle / "install.sh"), "--yes"],
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NAV_INSTALLER_TEST_MODE": "1",
            "NAV_INSTALLER_TEST_EUID": "0",
            "NAV_INSTALLER_TEST_OS": "Linux",
            "NAV_INSTALLER_TEST_ARCH": "x86_64",
            "NAV_TEST_COMMAND_LOG": str(log),
        },
    )

    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not log.exists() or "docker load" not in log.read_text()


def _installer_env(tmp_path: Path, fake_bin: Path) -> dict[str, str]:
    return os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "NAV_INSTALLER_TEST_MODE": "1",
        "NAV_INSTALLER_TEST_EUID": "0",
        "NAV_INSTALLER_TEST_OS": "Linux",
        "NAV_INSTALLER_TEST_ARCH": "x86_64",
        "NAV_TEST_COMMAND_LOG": str(tmp_path / "commands.log"),
    }


def test_first_install_writes_runtime_state_and_never_logs_password(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    install_dir = tmp_path / "installed"
    data_dir = tmp_path / "persistent-data"
    password_file = tmp_path / "initial-password"
    password_file.write_text("sensitive-passphrase\n")
    password_file.chmod(0o600)

    result = subprocess.run(
        [
            "bash",
            str(bundle / "install.sh"),
            "--listen",
            "0.0.0.0",
            "--port",
            "18080",
            "--install-dir",
            str(install_dir),
            "--data-dir",
            str(data_dir),
            "--username",
            "admin",
            "--password-file",
            str(password_file),
            "--yes",
        ],
        capture_output=True,
        text=True,
        env=_installer_env(tmp_path, fake_bin),
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "compose.yaml").is_file()
    assert (install_dir / "config/bookmark_policy.json").is_file()
    assert (data_dir / ".bookmark-navigation-data").read_text().strip() == (
        "private-bookmark-navigation-data-v1"
    )
    assert "phase=installed" in (install_dir / "install-state").read_text()
    env_text = (install_dir / ".env").read_text()
    assert "NAV_BIND_ADDRESS=0.0.0.0" in env_text
    assert "NAV_PORT=18080" in env_text
    assert f"NAV_DATA_DIR={data_dir}" in env_text
    assert "NAV_IMAGE_TAG=0.2.0" in env_text
    assert "sensitive-passphrase" not in env_text
    assert not (data_dir / ".navigation-initial-password").exists()

    command_log = (tmp_path / "commands.log").read_text()
    assert "docker load -i" in command_log
    assert "alembic upgrade head" in command_log
    assert "python -m app.main create-user --username admin" in command_log
    assert " up -d --wait" in command_log
    assert "chown -R 10001:10001" in command_log
    combined_output = result.stdout + result.stderr + command_log
    assert "sensitive-passphrase" not in combined_output


def test_occupied_port_is_rejected_before_image_load(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    password_file = tmp_path / "password"
    password_file.write_text("port-test-secret\n")
    password_file.chmod(0o600)
    env = _installer_env(tmp_path, fake_bin) | {
        "NAV_TEST_SS_OUTPUT": "LISTEN 0 128 0.0.0.0:18080 0.0.0.0:*"
    }
    result = subprocess.run(
        [
            "bash",
            str(bundle / "install.sh"),
            "--port",
            "18080",
            "--install-dir",
            str(tmp_path / "installed"),
            "--password-file",
            str(password_file),
            "--yes",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "port 18080 is already in use" in result.stderr
    log = tmp_path / "commands.log"
    assert not log.exists() or "docker load" not in log.read_text()


def test_first_install_avoids_overlapping_existing_docker_subnet(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    password_file = tmp_path / "password"
    password_file.write_text("network-test-secret\n")
    password_file.chmod(0o600)
    install_dir = tmp_path / "installed"
    env = _installer_env(tmp_path, fake_bin) | {
        "NAV_TEST_NETWORK_ID": "existing-network",
        "NAV_TEST_NETWORK_SUBNETS": "172.30.0.0/16",
    }
    result = subprocess.run(
        [
            "bash",
            str(bundle / "install.sh"),
            "--install-dir",
            str(install_dir),
            "--password-file",
            str(password_file),
            "--yes",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    env_text = (install_dir / ".env").read_text()
    assert "NAV_DOCKER_SUBNET=172.31.0.0/24" in env_text
    assert "NAV_DOCKER_GATEWAY=172.31.0.1" in env_text
    assert "NAV_APP_IP=172.31.0.2" in env_text


def test_first_install_rejects_group_readable_password_file(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    password_file = tmp_path / "password"
    password_file.write_text("not-private-enough\n")
    password_file.chmod(0o640)
    result = subprocess.run(
        [
            "bash",
            str(bundle / "install.sh"),
            "--install-dir",
            str(tmp_path / "installed"),
            "--password-file",
            str(password_file),
            "--yes",
        ],
        capture_output=True,
        text=True,
        env=_installer_env(tmp_path, fake_bin),
    )

    assert result.returncode != 0
    assert "must not be accessible by group or other users" in result.stderr
    log = tmp_path / "commands.log"
    assert not log.exists() or "docker load" not in log.read_text()


def test_upgrade_preserves_data_and_credentials_and_can_change_port(tmp_path):
    bundle, fake_bin = _make_fake_bundle(tmp_path)
    install_dir = tmp_path / "installed"
    data_dir = tmp_path / "persistent-data"
    password_file = tmp_path / "initial-password"
    password_file.write_text("first-secret\n")
    password_file.chmod(0o600)
    common = [
        "--install-dir",
        str(install_dir),
        "--data-dir",
        str(data_dir),
        "--password-file",
        str(password_file),
        "--yes",
    ]
    env = _installer_env(tmp_path, fake_bin)
    first = subprocess.run(
        ["bash", str(bundle / "install.sh"), *common],
        capture_output=True,
        text=True,
        env=env,
    )
    assert first.returncode == 0, first.stderr

    database = data_dir / "navigation.db"
    database.write_text("sentinel-bookmark-data")
    installed_policy = install_dir / "config/bookmark_policy.json"
    installed_policy.write_text('{"user_customized": true}\n')
    password_file.write_text("should-not-reset-account\n")
    second = subprocess.run(
        [
            "bash",
            str(bundle / "install.sh"),
            "--install-dir",
            str(install_dir),
            "--port",
            "19090",
            "--username",
            "different-user",
            "--password-file",
            str(password_file),
            "--yes",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert second.returncode == 0, second.stderr
    assert database.read_text() == "sentinel-bookmark-data"
    backups = list((data_dir / "backups").glob("pre-upgrade-*.db"))
    assert len(backups) == 1
    assert backups[0].read_text() == "sentinel-bookmark-data"
    assert "NAV_PORT=19090" in (install_dir / ".env").read_text()
    assert installed_policy.read_text() == '{"user_customized": true}\n'
    assert (install_dir / "config/bookmark_policy.json.package-new").is_file()
    assert "will not modify the existing account" in second.stderr

    command_log = (tmp_path / "commands.log").read_text()
    assert command_log.count("python -m app.main create-user") == 1
    assert "docker " in command_log and " stop bookmark-navigation" in command_log


def _make_builder_docker(tmp_path: Path, platform: str = "linux/amd64") -> Path:
    fake_bin = tmp_path / "builder-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docker %s\\n' \"$*\" >> \"$NAV_TEST_COMMAND_LOG\"\n"
        "if [ \"${1:-}\" = image ] && [ \"${2:-}\" = inspect ]; then\n"
        f"  echo '{platform}'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = save ] && [ \"${2:-}\" = -o ]; then\n"
        "  printf 'exported image' > \"$3\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    docker.chmod(0o755)
    return fake_bin


def test_bundle_builder_help_and_required_image_argument():
    help_result = subprocess.run(
        ["bash", str(BUILDER), "--help"], capture_output=True, text=True
    )
    missing_image = subprocess.run(
        ["bash", str(BUILDER)], capture_output=True, text=True
    )

    assert help_result.returncode == 0
    assert "--image IMAGE" in help_result.stdout
    assert "--output-dir PATH" in help_result.stdout
    assert missing_image.returncode != 0
    assert "--image is required" in missing_image.stderr


def test_bundle_builder_exports_verified_amd64_image_and_checksums(tmp_path):
    fake_bin = _make_builder_docker(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    log = tmp_path / "builder.log"
    result = subprocess.run(
        [
            "bash",
            str(BUILDER),
            "--image",
            "bookmark-navigation:2026-07-14-r2",
            "--version",
            "2026.07.15-r1-test",
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NAV_TEST_COMMAND_LOG": str(log),
        },
    )

    assert result.returncode == 0, result.stderr
    archive = output_dir / "bookmark-navigation-offline-amd64-2026.07.15-r1-test.tar.gz"
    assert archive.is_file()
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    subprocess.run(["tar", "-xzf", str(archive), "-C", str(extract_dir)], check=True)
    release_dir = extract_dir / "bookmark-navigation-offline-amd64-2026.07.15-r1-test"
    assert (release_dir / "image/bookmark-navigation-amd64.tar").read_text() == (
        "exported image"
    )
    assert (release_dir / "config/bookmark_policy.json").is_file()
    assert os.access(release_dir / "install.sh", os.X_OK)
    manifest = (release_dir / "MANIFEST").read_text()
    assert "version=2026.07.15-r1-test" in manifest
    assert "image_repository=bookmark-navigation" in manifest
    assert "image_tag=2026-07-14-r2" in manifest
    checksum = subprocess.run(
        ["shasum", "-a", "256", "-c", "SHA256SUMS"],
        cwd=release_dir,
        capture_output=True,
        text=True,
    )
    assert checksum.returncode == 0, checksum.stderr
    commands = log.read_text()
    assert "docker image inspect" in commands
    assert "docker save -o" in commands


def test_bundle_builder_rejects_non_amd64_image_before_export(tmp_path):
    fake_bin = _make_builder_docker(tmp_path, platform="linux/arm64")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    log = tmp_path / "builder.log"
    result = subprocess.run(
        [
            "bash",
            str(BUILDER),
            "--image",
            "bookmark-navigation:arm64",
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NAV_TEST_COMMAND_LOG": str(log),
        },
    )

    assert result.returncode != 0
    assert "requires a linux/amd64 image" in result.stderr
    assert "docker save" not in log.read_text()


def test_offline_deployment_documentation_covers_install_upgrade_and_operations():
    deployment = (RELEASE_ROOT / "docs/DEPLOYMENT.md").read_text()
    readme = (NAVIGATION_ROOT / "README.md").read_text()
    server_record = (
        NAVIGATION_ROOT / "docs/linux-server-deployment-2026-07-14.md"
    ).read_text()

    for expected in (
        "sudo ./install.sh --listen 127.0.0.1 --port 8080",
        "--password-file",
        "原地升级",
        "bookmark-navigation/data/backups",
        "docker compose",
        "0.0.0.0",
        "linux/amd64",
    ):
        assert expected in deployment
    assert "release/docs/DEPLOYMENT.md" in readme
    assert "build-offline-bundle.sh" in readme
    assert "离线安装包" in server_record
