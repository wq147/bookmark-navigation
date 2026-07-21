#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

LISTEN_ADDRESS="127.0.0.1"
PORT="8080"
INSTALL_DIR="/opt/bookmark-navigation"
DATA_DIR=""
USERNAME="admin"
PASSWORD_FILE=""
LISTEN_EXPLICIT=0
PORT_EXPLICIT=0
DATA_DIR_EXPLICIT=0
USERNAME_EXPLICIT=0
PASSWORD_FILE_EXPLICIT=0

STATE_FILE=""
ENV_FILE=""
PROJECT_NAME=""
IMAGE_REPOSITORY=""
IMAGE_TAG=""
IMAGE_ARCHIVE=""
DOCKER_SUBNET=""
DOCKER_GATEWAY=""
APP_IP=""

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh [OPTIONS]

Install or upgrade Bookmark Navigation from an offline amd64 bundle.

Options:
  --listen ADDRESS       Host listen address (default: 127.0.0.1)
  --port PORT            Host published port (default: 8080)
  --install-dir PATH     Runtime files directory (default: /opt/bookmark-navigation)
  --data-dir PATH        Persistent data directory (default: INSTALL_DIR/data)
  --username USER        Initial administrator username (default: admin)
  --password-file FILE   Read the initial password from FILE
  --yes                  Skip non-sensitive confirmation prompts
  --help                 Show this help
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_value() {
  local option="${1:?option is required}"
  local value="${2-}"
  [[ -n "$value" && "$value" != --* ]] || die "$option requires a value"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --listen)
        require_value "$1" "${2-}"
        LISTEN_ADDRESS="$2"
        LISTEN_EXPLICIT=1
        shift 2
        ;;
      --port)
        require_value "$1" "${2-}"
        PORT="$2"
        PORT_EXPLICIT=1
        shift 2
        ;;
      --install-dir)
        require_value "$1" "${2-}"
        INSTALL_DIR="$2"
        shift 2
        ;;
      --data-dir)
        require_value "$1" "${2-}"
        DATA_DIR="$2"
        DATA_DIR_EXPLICIT=1
        shift 2
        ;;
      --username)
        require_value "$1" "${2-}"
        USERNAME="$2"
        USERNAME_EXPLICIT=1
        shift 2
        ;;
      --password-file)
        require_value "$1" "${2-}"
        PASSWORD_FILE="$2"
        PASSWORD_FILE_EXPLICIT=1
        shift 2
        ;;
      --yes)
        shift
        ;;
      --help)
        usage
        exit 0
        ;;
      --*) die "Unknown option: $1" ;;
      *) die "Unexpected argument: $1" ;;
    esac
  done
}

validate_args() {
  [[ "$PORT" =~ ^[0-9]+$ ]] && ((10#$PORT >= 1 && 10#$PORT <= 65535)) \
    || die "Invalid port: $PORT (expected 1-65535)"
  validate_ipv4 "$LISTEN_ADDRESS" || die "Invalid listen address: expected an IPv4 address"
  [[ "$INSTALL_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || die "Invalid install directory: use a simple absolute Linux path"
  if [[ -z "$DATA_DIR" ]]; then
    DATA_DIR="$INSTALL_DIR/data"
  fi
  [[ "$DATA_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || die "Invalid data directory: use a simple absolute Linux path"
  case "$INSTALL_DIR" in
    /|/opt|/home|/var|/var/lib|*/../*|*/..) die "unsafe install directory: $INSTALL_DIR" ;;
  esac
  case "$DATA_DIR" in
    /|/opt|/home|/var|/var/lib|*/../*|*/..) die "unsafe data directory: $DATA_DIR" ;;
  esac
  [[ "$DATA_DIR" != "$INSTALL_DIR" ]] || die "data directory must differ from install directory"
  [[ "$USERNAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "Invalid username"
  if [[ -n "$PASSWORD_FILE" ]]; then
    [[ -r "$PASSWORD_FILE" && -f "$PASSWORD_FILE" ]] \
      || die "Password file is not a readable regular file: $PASSWORD_FILE"
    require_command stat
    local password_mode
    password_mode="$(stat -c '%a' -- "$PASSWORD_FILE")" \
      || die "cannot inspect password file permissions"
    [[ "$password_mode" =~ ^[0-7]+$ ]] \
      || die "cannot inspect password file permissions"
    (((8#$password_mode & 077) == 0)) \
      || die "password file must not be accessible by group or other users"
  fi
}

canonicalize_paths() {
  require_command realpath
  INSTALL_DIR="$(realpath -m -- "$INSTALL_DIR")" || die "cannot resolve install directory"
  DATA_DIR="$(realpath -m -- "$DATA_DIR")" || die "cannot resolve data directory"
  case "$INSTALL_DIR" in
    /|/opt|/home|/var|/var/lib) die "unsafe install directory: $INSTALL_DIR" ;;
  esac
  case "$DATA_DIR" in
    /|/opt|/home|/var|/var/lib) die "unsafe data directory: $DATA_DIR" ;;
  esac
  case "$INSTALL_DIR" in
    "$DATA_DIR"/*) die "install directory must not be inside the data directory" ;;
  esac
}

validate_ipv4() {
  local address="${1-}"
  local a b c d extra
  IFS=. read -r a b c d extra <<<"$address"
  [[ -z "${extra:-}" && -n "${a:-}" && -n "${b:-}" && -n "${c:-}" && -n "${d:-}" ]] || return 1
  local octet
  for octet in "$a" "$b" "$c" "$d"; do
    [[ "$octet" =~ ^[0-9]{1,3}$ ]] || return 1
    ((10#$octet <= 255)) || return 1
  done
}

require_root_and_platform() {
  local effective_uid="$EUID"
  local system_name
  local machine_arch
  if [[ "${NAV_INSTALLER_TEST_MODE:-0}" == "1" ]]; then
    effective_uid="${NAV_INSTALLER_TEST_EUID:-$effective_uid}"
    system_name="${NAV_INSTALLER_TEST_OS:-$(uname -s)}"
    machine_arch="${NAV_INSTALLER_TEST_ARCH:-$(uname -m)}"
  else
    system_name="$(uname -s)"
    machine_arch="$(uname -m)"
  fi
  ((effective_uid == 0)) || die "installer must run as root (use sudo)"
  [[ "$system_name" == "Linux" && ( "$machine_arch" == "x86_64" || "$machine_arch" == "amd64" ) ]] \
    || die "this bundle requires Linux amd64 (found $system_name/$machine_arch)"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

verify_checksums() {
  [[ -f "$SCRIPT_DIR/SHA256SUMS" ]] || die "missing SHA256SUMS"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && sha256sum -c SHA256SUMS >/dev/null) \
      || die "release checksum verification failed"
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && shasum -a 256 -c SHA256SUMS >/dev/null) \
      || die "release checksum verification failed"
  else
    die "required command not found: sha256sum"
  fi
}

preflight() {
  require_command docker
  require_command ss
  require_command curl
  require_command awk
  require_command cksum
  require_command cmp
  require_command find
  require_command install
  docker info >/dev/null 2>&1 || die "Docker Engine is unavailable"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable"
  verify_checksums
}

manifest_value() {
  local key="${1:?manifest key is required}"
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; found=1} END {if (!found) exit 1}' \
    "$SCRIPT_DIR/MANIFEST"
}

load_manifest() {
  IMAGE_REPOSITORY="$(manifest_value image_repository)" || die "invalid MANIFEST: image_repository"
  IMAGE_TAG="$(manifest_value image_tag)" || die "invalid MANIFEST: image_tag"
  IMAGE_ARCHIVE="$(manifest_value image_archive)" || die "invalid MANIFEST: image_archive"
  [[ "$IMAGE_ARCHIVE" == image/* && "$IMAGE_ARCHIVE" != *..* ]] \
    || die "invalid MANIFEST image archive path"
  [[ -f "$SCRIPT_DIR/$IMAGE_ARCHIVE" ]] || die "missing image archive: $IMAGE_ARCHIVE"
}

state_value() {
  local key="${1:?state key is required}"
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; found=1} END {if (!found) exit 1}' "$STATE_FILE"
}

env_value() {
  local key="${1:?environment key is required}"
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; found=1} END {if (!found) exit 1}' "$ENV_FILE"
}

directory_is_nonempty() {
  [[ -d "$1" ]] && [[ -n "$(find "$1" -mindepth 1 -maxdepth 1 -print -quit)" ]]
}

port_is_in_use() {
  ss -H -ltn | awk -v port="$1" '$4 ~ (":" port "$") {found=1} END {exit !found}'
}

derive_project_name() {
  local identifier
  identifier="$(printf '%s' "$INSTALL_DIR" | cksum | awk '{print $1}')"
  PROJECT_NAME="bookmark-navigation-$identifier"
}

ip_to_int() {
  local a b c d
  IFS=. read -r a b c d <<<"$1"
  printf '%u\n' "$(( (10#$a << 24) + (10#$b << 16) + (10#$c << 8) + 10#$d ))"
}

cidr_bounds() {
  local cidr="$1"
  local address="${cidr%/*}"
  local prefix="${cidr#*/}"
  validate_ipv4 "$address" || return 1
  [[ "$prefix" =~ ^[0-9]+$ ]] && ((10#$prefix >= 0 && 10#$prefix <= 32)) || return 1
  local value size start end
  value="$(ip_to_int "$address")"
  size=$((1 << (32 - 10#$prefix)))
  start=$((value / size * size))
  end=$((start + size - 1))
  printf '%s %s\n' "$start" "$end"
}

cidr_overlaps() {
  local first second
  first="$(cidr_bounds "$1")" || return 1
  second="$(cidr_bounds "$2")" || return 1
  local first_start first_end second_start second_end
  read -r first_start first_end <<<"$first"
  read -r second_start second_end <<<"$second"
  ((first_start <= second_end && second_start <= first_end))
}

select_network() {
  local used_subnets=""
  local network_id subnet candidate conflict third
  while IFS= read -r network_id; do
    [[ -n "$network_id" ]] || continue
    while IFS= read -r subnet; do
      [[ -n "$subnet" ]] && used_subnets+="$subnet"$'\n'
    done < <(docker network inspect "$network_id" --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}')
  done < <(docker network ls -q)

  for third in {30..39}; do
    candidate="172.$third.0.0/24"
    conflict=0
    while IFS= read -r subnet; do
      [[ "$subnet" == *.*/* ]] || continue
      if cidr_overlaps "$candidate" "$subnet"; then
        conflict=1
        break
      fi
    done <<<"$used_subnets"
    if ((conflict == 0)); then
      DOCKER_SUBNET="$candidate"
      DOCKER_GATEWAY="172.$third.0.1"
      APP_IP="172.$third.0.2"
      return 0
    fi
  done
  die "unable to find an unused Docker bridge subnet"
}

write_env_file() {
  local temporary="$INSTALL_DIR/.env.tmp.$$"
  umask 077
  {
    echo 'DATABASE_URL=sqlite:////data/navigation.db'
    echo 'NAV_BACKUP_DIR=/data/backups'
    echo 'NAV_BOOKMARK_POLICY_PATH=/config/bookmark_policy.json'
    echo 'NAV_IMPORT_MAX_BYTES=2097152'
    echo 'NAV_IMPORT_BATCH_TTL_SECONDS=86400'
    echo "NAV_TRUSTED_PROXY_IPS=$DOCKER_GATEWAY"
    echo "NAV_BIND_ADDRESS=$LISTEN_ADDRESS"
    echo "NAV_PORT=$PORT"
    echo "NAV_DATA_DIR=$DATA_DIR"
    echo "NAV_POLICY_PATH=$INSTALL_DIR/config/bookmark_policy.json"
    echo "NAV_IMAGE_REPOSITORY=$IMAGE_REPOSITORY"
    echo "NAV_IMAGE_TAG=$IMAGE_TAG"
    echo "NAV_DOCKER_SUBNET=$DOCKER_SUBNET"
    echo "NAV_DOCKER_GATEWAY=$DOCKER_GATEWAY"
    echo "NAV_APP_IP=$APP_IP"
    echo 'NAV_INITIAL_PASSWORD_FILE=/data/.navigation-initial-password'
  } >"$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$ENV_FILE"
}

write_state() {
  local phase="${1:?state phase is required}"
  local temporary="$INSTALL_DIR/install-state.tmp.$$"
  umask 077
  {
    echo 'format=1'
    echo "phase=$phase"
    echo "version=$(<"$SCRIPT_DIR/VERSION")"
    echo "install_dir=$INSTALL_DIR"
    echo "data_dir=$DATA_DIR"
    echo "project_name=$PROJECT_NAME"
  } >"$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$STATE_FILE"
}

compose() {
  docker compose --project-directory "$INSTALL_DIR" -p "$PROJECT_NAME" \
    --env-file "$ENV_FILE" -f "$INSTALL_DIR/compose.yaml" "$@"
}

copy_runtime_files() {
  install -m 644 "$SCRIPT_DIR/compose.yaml" "$INSTALL_DIR/compose.yaml"
  install -d -m 700 "$INSTALL_DIR/config"
  if [[ ! -f "$INSTALL_DIR/config/bookmark_policy.json" ]]; then
    install -m 644 "$SCRIPT_DIR/config/bookmark_policy.json" \
      "$INSTALL_DIR/config/bookmark_policy.json"
  elif ! cmp -s "$SCRIPT_DIR/config/bookmark_policy.json" \
      "$INSTALL_DIR/config/bookmark_policy.json"; then
    install -m 644 "$SCRIPT_DIR/config/bookmark_policy.json" \
      "$INSTALL_DIR/config/bookmark_policy.json.package-new"
    echo "Warning: preserved customized bookmark_policy.json; package version saved as bookmark_policy.json.package-new" >&2
  fi
}

prepare_fresh_install() {
  if directory_is_nonempty "$INSTALL_DIR"; then
    die "refusing non-empty install directory without valid install-state: $INSTALL_DIR"
  fi
  if directory_is_nonempty "$DATA_DIR"; then
    die "refusing non-empty unmarked data directory: $DATA_DIR"
  fi
  install -d -m 700 "$INSTALL_DIR" "$DATA_DIR"
  printf 'private-bookmark-navigation-data-v1\n' >"$DATA_DIR/.bookmark-navigation-data"
  chmod 600 "$DATA_DIR/.bookmark-navigation-data"
  chown -R 10001:10001 "$DATA_DIR"
  select_network
  derive_project_name
  STATE_FILE="$INSTALL_DIR/install-state"
  ENV_FILE="$INSTALL_DIR/.env"
  copy_runtime_files
  write_env_file
  write_state installing
}

load_existing_install() {
  STATE_FILE="$INSTALL_DIR/install-state"
  ENV_FILE="$INSTALL_DIR/.env"
  [[ -f "$STATE_FILE" && -f "$ENV_FILE" ]] \
    || die "existing install is missing install-state or .env"
  [[ "$(state_value format)" == "1" ]] || die "unsupported install-state format"
  [[ "$(state_value install_dir)" == "$INSTALL_DIR" ]] || die "install-state directory mismatch"
  PROJECT_NAME="$(state_value project_name)" || die "install-state is missing project_name"
  local installed_data_dir
  installed_data_dir="$(state_value data_dir)" || die "install-state is missing data_dir"
  if ((DATA_DIR_EXPLICIT)); then
    [[ "$DATA_DIR" == "$installed_data_dir" ]] \
      || die "changing the data directory during upgrade is not supported"
  else
    DATA_DIR="$installed_data_dir"
  fi
  [[ -f "$DATA_DIR/.bookmark-navigation-data" ]] \
    || die "existing data directory is unmarked"
  [[ "$(<"$DATA_DIR/.bookmark-navigation-data")" == "private-bookmark-navigation-data-v1" ]] \
    || die "existing data marker is invalid"

  local installed_listen installed_port
  installed_listen="$(env_value NAV_BIND_ADDRESS)"
  installed_port="$(env_value NAV_PORT)"
  ((LISTEN_EXPLICIT)) || LISTEN_ADDRESS="$installed_listen"
  ((PORT_EXPLICIT)) || PORT="$installed_port"
  DOCKER_SUBNET="$(env_value NAV_DOCKER_SUBNET)"
  DOCKER_GATEWAY="$(env_value NAV_DOCKER_GATEWAY)"
  APP_IP="$(env_value NAV_APP_IP)"

  if ((USERNAME_EXPLICIT || PASSWORD_FILE_EXPLICIT)); then
    echo "Warning: --username/--password-file will not modify the existing account during upgrade." >&2
  fi

  if [[ "$LISTEN_ADDRESS" != "$installed_listen" || "$PORT" != "$installed_port" ]]; then
    if port_is_in_use "$PORT"; then
      die "port $PORT is already in use"
    fi
  fi
}

read_initial_password() {
  local first second
  if [[ -n "$PASSWORD_FILE" ]]; then
    first="$(<"$PASSWORD_FILE")"
  else
    [[ -t 0 ]] || die "first install requires --password-file when no interactive terminal is available"
    read -r -s -p 'Initial administrator password: ' first
    echo >&2
    read -r -s -p 'Confirm password: ' second
    echo >&2
    [[ "$first" == "$second" ]] || die "password confirmation does not match"
  fi
  [[ -n "$first" ]] || die "initial password cannot be empty"
  printf '%s' "$first"
}

start_and_verify() {
  if ! compose up -d --wait; then
    compose ps >&2 || true
    compose logs --tail 100 bookmark-navigation >&2 || true
    die "service failed to become healthy"
  fi
  local health_host="$LISTEN_ADDRESS"
  [[ "$health_host" != "0.0.0.0" ]] || health_host="127.0.0.1"
  if ! curl --fail --silent --show-error --max-time 5 \
      "http://$health_host:$PORT/healthz" >/dev/null; then
    compose ps >&2 || true
    compose logs --tail 100 bookmark-navigation >&2 || true
    die "health endpoint verification failed"
  fi
}

run_first_install() {
  local initial_password temporary_password
  initial_password="$(read_initial_password)"
  docker load -i "$SCRIPT_DIR/$IMAGE_ARCHIVE" >/dev/null
  compose run --rm bookmark-navigation alembic upgrade head
  temporary_password="$DATA_DIR/.navigation-initial-password"
  cleanup_initial_password() {
    rm -f -- "$temporary_password"
  }
  trap cleanup_initial_password EXIT
  trap 'exit 130' HUP INT TERM
  umask 077
  printf '%s' "$initial_password" >"$temporary_password"
  unset initial_password
  chown 10001:10001 "$temporary_password"
  chmod 600 "$temporary_password"
  compose run --rm bookmark-navigation python -m app.main create-user --username "$USERNAME"
  cleanup_initial_password
  trap - EXIT HUP INT TERM
  write_state installed
  start_and_verify
}

run_upgrade() {
  local backup_file
  [[ -f "$DATA_DIR/navigation.db" ]] || die "existing installation has no navigation.db"
  docker load -i "$SCRIPT_DIR/$IMAGE_ARCHIVE" >/dev/null
  copy_runtime_files
  write_env_file
  compose stop bookmark-navigation
  install -d -m 700 "$DATA_DIR/backups"
  backup_file="$DATA_DIR/backups/pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ)-$$.db"
  cp -p "$DATA_DIR/navigation.db" "$backup_file"
  chown 10001:10001 "$backup_file"
  if ! compose run --rm bookmark-navigation alembic upgrade head; then
    die "database migration failed; service remains stopped; backup: $backup_file"
  fi
  write_state installed
  start_and_verify
  echo "Upgrade backup: $backup_file"
}

install_or_upgrade() {
  local existing=0 current_phase=""
  STATE_FILE="$INSTALL_DIR/install-state"
  if [[ -f "$STATE_FILE" ]]; then
    existing=1
    current_phase="$(state_value phase)" || die "install-state is missing phase"
  elif directory_is_nonempty "$INSTALL_DIR"; then
    die "refusing non-empty install directory without valid install-state: $INSTALL_DIR"
  fi

  if ((existing)); then
    load_existing_install
  else
    if port_is_in_use "$PORT"; then
      die "port $PORT is already in use"
    fi
    prepare_fresh_install
  fi

  if ((existing)) && [[ "$current_phase" == "installed" ]]; then
    run_upgrade
    echo "Bookmark Navigation upgraded successfully."
  elif ((existing)) && [[ "$current_phase" != "installing" ]]; then
    die "invalid install phase: $current_phase"
  else
    run_first_install
    echo "Bookmark Navigation installed successfully."
  fi
  if [[ "$LISTEN_ADDRESS" == "0.0.0.0" ]]; then
    echo "Access: http://<server-ip>:$PORT"
  else
    echo "Access: http://$LISTEN_ADDRESS:$PORT"
  fi
  echo "Install directory: $INSTALL_DIR"
  echo "Data directory: $DATA_DIR"
}

main() {
  parse_args "$@"
  validate_args
  require_root_and_platform
  canonicalize_paths
  preflight
  load_manifest
  install_or_upgrade
}

main "$@"
