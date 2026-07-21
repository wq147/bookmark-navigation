#!/usr/bin/env bash

# Shared guards for the standalone deployment commands documented in README.md.

resolve_data_dir() {
  docker compose config --format json | python3 -c '
import json, pathlib, sys
config = json.load(sys.stdin)
volumes = config["services"]["bookmark-navigation"].get("volumes", [])
sources = [item.get("source") for item in volumes if item.get("target") == "/data"]
if len(sources) != 1 or not sources[0]:
    raise SystemExit("expected exactly one /data bind source")
path = pathlib.Path(sources[0])
resolved = path.resolve()
blocked = {
    pathlib.Path("/"), pathlib.Path.cwd().resolve(), pathlib.Path.home().resolve(),
    pathlib.Path("/home").resolve(), pathlib.Path("/var/lib").resolve(),
}
if not path.is_absolute() or resolved in blocked:
    raise SystemExit("refusing unsafe NAV_DATA_DIR")
print(resolved)'
}

resolve_nav_port() {
  docker compose config --format json | python3 -c '
import json, sys
config = json.load(sys.stdin)
ports = config["services"]["bookmark-navigation"].get("ports", [])
values = [str(item.get("published", "")) for item in ports if str(item.get("target")) == "8080"]
if len(values) != 1 or not values[0].isdigit() or not 1 <= int(values[0]) <= 65535:
    raise SystemExit("expected one valid published NAV_PORT")
print(values[0])'
}

require_data_marker() {
  local data_dir="${1:?DATA_DIR is required}"
  if ! sudo test -f "$data_dir/.bookmark-navigation-data" ||
     [ "$(sudo cat "$data_dir/.bookmark-navigation-data")" != 'private-bookmark-navigation-data-v1' ]; then
    echo 'refusing unmarked DATA_DIR' >&2
    return 1
  fi
}

require_outside_data_tree() {
  local data_dir candidate
  data_dir="$(realpath -e -- "${1:?DATA_DIR is required}")"
  candidate="$(realpath -m -- "${2:?archive path is required}")"
  [ "$candidate" != / ] || { echo 'refusing root archive path' >&2; return 1; }
  case "$candidate" in
    "$data_dir"|"$data_dir"/*)
      echo 'backup output must be outside DATA_DIR; restore archives must also remain outside' >&2
      return 1
      ;;
  esac
  printf '%s\n' "$candidate"
}
