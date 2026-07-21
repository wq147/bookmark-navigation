#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly NAVIGATION_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

IMAGE_REF=""
VERSION="$(<"$SCRIPT_DIR/VERSION")"
OUTPUT_DIR="$PWD"
TEMPORARY_DIR=""

usage() {
  cat <<'EOF'
Usage: ./build-offline-bundle.sh --image IMAGE [OPTIONS]

Export an existing Linux amd64 Docker image and assemble the offline installer.

Options:
  --image IMAGE          Existing Docker image reference to export (required)
  --version VERSION      Bundle version (default: release/VERSION)
  --output-dir PATH      Destination directory (default: current directory)
  --help                 Show this help
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_value() {
  [[ -n "${2-}" && "${2-}" != --* ]] || die "$1 requires a value"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --image)
        require_value "$1" "${2-}"
        IMAGE_REF="$2"
        shift 2
        ;;
      --version)
        require_value "$1" "${2-}"
        VERSION="$2"
        shift 2
        ;;
      --output-dir)
        require_value "$1" "${2-}"
        OUTPUT_DIR="$2"
        shift 2
        ;;
      --help)
        usage
        exit 0
        ;;
      --*) die "Unknown option: $1" ;;
      *) die "Unexpected argument: $1" ;;
    esac
  done
  [[ -n "$IMAGE_REF" ]] || die "--image is required"
  [[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid bundle version: $VERSION"
  [[ "$IMAGE_REF" != *@* ]] || die "image digests are not supported; use a tagged image"
  local last_component="${IMAGE_REF##*/}"
  [[ "$last_component" == *:* ]] || die "image reference must include an explicit tag"
}

checksum_files() {
  local release_dir="$1"
  local files=(
    install.sh
    compose.yaml
    VERSION
    MANIFEST
    docs/DEPLOYMENT.md
    config/bookmark_policy.json
    image/bookmark-navigation-amd64.tar
  )
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$release_dir" && sha256sum "${files[@]}") >"$release_dir/SHA256SUMS"
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$release_dir" && shasum -a 256 "${files[@]}") >"$release_dir/SHA256SUMS"
  else
    die "sha256sum or shasum is required"
  fi
}

cleanup() {
  if [[ -n "$TEMPORARY_DIR" && -d "$TEMPORARY_DIR" ]]; then
    rm -rf -- "$TEMPORARY_DIR"
  fi
}

main() {
  parse_args "$@"
  command -v docker >/dev/null 2>&1 || die "docker is required"
  command -v tar >/dev/null 2>&1 || die "tar is required"

  local platform
  platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE_REF" 2>/dev/null)" \
    || die "Docker image not found: $IMAGE_REF"
  [[ "$platform" == "linux/amd64" ]] \
    || die "offline bundle requires a linux/amd64 image (found $platform)"

  local image_tag="${IMAGE_REF##*:}"
  local image_repository="${IMAGE_REF%:*}"
  local policy_source="$NAVIGATION_ROOT/../bookmark_policy.json"
  [[ -f "$policy_source" ]] || die "bookmark policy not found: $policy_source"

  install -d -m 755 "$OUTPUT_DIR"
  local release_name release_dir archive
  TEMPORARY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bookmark-navigation-release.XXXXXX")"
  trap cleanup EXIT
  trap 'exit 130' HUP INT TERM
  release_name="bookmark-navigation-offline-amd64-$VERSION"
  release_dir="$TEMPORARY_DIR/$release_name"
  archive="$OUTPUT_DIR/$release_name.tar.gz"

  install -d -m 755 "$release_dir/image" "$release_dir/config" "$release_dir/docs"
  install -m 755 "$SCRIPT_DIR/install.sh" "$release_dir/install.sh"
  install -m 644 "$SCRIPT_DIR/compose.yaml" "$release_dir/compose.yaml"
  install -m 644 "$SCRIPT_DIR/docs/DEPLOYMENT.md" "$release_dir/docs/DEPLOYMENT.md"
  install -m 644 "$policy_source" "$release_dir/config/bookmark_policy.json"
  printf '%s\n' "$VERSION" >"$release_dir/VERSION"
  {
    echo 'name=bookmark-navigation'
    echo "version=$VERSION"
    echo 'platform=linux/amd64'
    echo "image_repository=$image_repository"
    echo "image_tag=$image_tag"
    echo 'image_archive=image/bookmark-navigation-amd64.tar'
  } >"$release_dir/MANIFEST"

  docker save -o "$release_dir/image/bookmark-navigation-amd64.tar" "$IMAGE_REF"
  checksum_files "$release_dir"
  tar -C "$TEMPORARY_DIR" -czf "$archive" "$release_name"

  echo "Offline bundle: $archive"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$archive"
  else
    shasum -a 256 "$archive"
  fi
}

main "$@"
