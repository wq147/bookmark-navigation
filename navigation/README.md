# Private Bookmark Navigation 源码构建与高级运维

这是多用户、私有部署的书签导航服务。单个 SQLite 数据库保存账号及彼此完全隔离的书签数据，并由唯一主管理员维护账号。本文面向修改源码、重新构建镜像、手工备份/恢复和回滚的维护者。**普通部署不应从本文开始**；在其他 Linux amd64 服务器首装或升级，优先阅读 [离线部署指南](release/docs/DEPLOYMENT.md)。

源码 Compose 模式下，生产环境只应将端口绑定到回环地址，由同机 Nginx 终止 HTTPS；不要把 `8080` 直接暴露到公网。

最新的真实 V5 数据验收结果、恢复演练和环境限制见 [2026-07-13 验收记录](docs/acceptance-2026-07-13.md)。Docker/Compose 仍必须在安装了 Docker 的原生 Linux 主机上按该记录的待办命令复验后，才能视为部署验收完成。

如果目标机只需运行已构建镜像，优先使用 [Linux amd64 离线安装包](release/docs/DEPLOYMENT.md)。`release/build-offline-bundle.sh` 从本机已有镜像生成包含镜像、安装器、Compose 和校验文件的 `tar.gz`；目标机可使用 `sudo ./install.sh --listen 127.0.0.1 --port 8080` 完成首装，之后重复执行安装器即可保留数据原地升级。

## 项目文件与目录作用

| 路径 | 作用 |
| --- | --- |
| `backend/` | FastAPI 应用、SQLite/Alembic 持久化、账号认证、书签导入导出、备份和 pytest 测试 |
| `frontend/` | Vue 3 三栏工作台、导入预览、编辑/搜索/备份界面、Vitest 与 Playwright 测试 |
| `Dockerfile` | 先构建前端静态文件，再生成以非 root UID `10001` 运行的 Python 镜像 |
| `compose.yaml` | 源码构建和手工部署 Compose，包含 `build:`，不是离线包内的运行 Compose |
| `.env.example` | 源码 Compose 模式的容器参数、宿主机绑定、数据目录和 Docker 网络模板 |
| `deploy/` | `navigation-ops.sh` 安全运维守卫和 `nginx.conf.example` 反向代理示例 |
| `release/` | 无 `build:` 的运行 Compose、一键安装/升级脚本、离线包构建器、版本、发布清单和随包文档 |
| `docs/` | 功能验收、历史服务器部署记录、已确认设计与实施计划 |

## 本地开发与验证

根目录 `.python-version` 固定 Python `3.13.14`，`.node-version` 固定 Node.js `v24.18.0`。后端依赖由 `pyproject.toml` 声明并由 `uv.lock` 锁定；前端依赖由 `package-lock.json` 锁定。以下命令分别从指定目录运行，不需要全局安装 Python 或 Node 依赖：

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --extra test
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -W error -m pytest -q
```

```bash
cd navigation/frontend
fnm exec --using ../../.node-version npm ci
fnm exec --using ../../.node-version npm test -- --run
fnm exec --using ../../.node-version npm run typecheck
fnm exec --using ../../.node-version npm run build
```

前端开发服务器使用 `npm run dev`，并把 `/api` 代理到 `http://127.0.0.1:8000`。后端可从 `navigation/backend` 以 `uv run uvicorn app.main:app --reload` 启动；默认数据库是该目录下的 `navigation.db`，首次使用前仍需运行 Alembic 迁移并创建管理员。登录 Cookie 默认要求 HTTPS，纯 HTTP 的本地交互验收应使用隔离测试配置，不能把 `NAV_TEST_MODE=1` 带入部署环境。

Python 3.13 下全局 `-W error` 是当前后端测试基线；原生 SQLite 连接和测试 engine 必须确定性释放，不得通过忽略 `ResourceWarning` 规避回归。Playwright E2E 需要额外浏览器和可访问的测试服务；Docker Compose 配置、镜像和健康检查必须在安装了 Docker 的环境复验。

## 首次初始化

1. 在原生 Linux Docker 主机上确认 `../bookmark_policy.json` 存在，复制配置，编辑后限制读权限：

   ```bash
   set -euo pipefail
   source ./deploy/navigation-ops.sh
   cp .env.example .env
   chmod 600 .env
   ${EDITOR:-vi} .env
   ```

   容器内键为 `DATABASE_URL`、`NAV_BACKUP_DIR`、`NAV_BOOKMARK_POLICY_PATH`、`NAV_IMPORT_MAX_BYTES`、`NAV_IMPORT_BATCH_TTL_SECONDS` 和仅初始化命令使用的 `NAV_INITIAL_PASSWORD_FILE`；Compose 主机键为 `NAV_BIND_ADDRESS`、`NAV_PORT`、`NAV_DATA_DIR`、`NAV_IMAGE_TAG`。保持 `NAV_BIND_ADDRESS=127.0.0.1`。

2. 后续命令都从 `navigation` 目录运行，并在各自的新 Bash 会话中启用 fail-fast 模式、加载已提交的 `deploy/navigation-ops.sh`。该文件不会 `source .env`，而是读取 Compose 完成默认值和 `.env` 插值后的最终配置；数据目录必须是唯一的、绝对的非根目录，端口必须是 1–65535。不要跳过任一代码块开头的 `set` 或 `source`。

3. **在任何容器写入前**，解析 bind mount 并强制设置容器非 root 用户 UID/GID 10001 的所有权和严格模式。这是必做步骤，不是权限报错后的可选修复：

   ```bash
   set -euo pipefail
   source ./deploy/navigation-ops.sh
   DATA_DIR="$(resolve_data_dir)"
   if sudo test -e "$DATA_DIR"; then
     sudo test -d "$DATA_DIR" || { echo 'DATA_DIR is not a directory' >&2; exit 1; }
     if [ -n "$(sudo find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
       echo 'refusing non-empty unmarked DATA_DIR' >&2
       exit 1
     fi
   else
     sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR"
   fi
   printf 'private-bookmark-navigation-data-v1\n' | sudo tee "$DATA_DIR/.bookmark-navigation-data" >/dev/null
   sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR/backups"
   sudo chown -R 10001:10001 "$DATA_DIR"
   sudo chmod 700 "$DATA_DIR" "$DATA_DIR/backups"
   sudo chmod 600 "$DATA_DIR/.bookmark-navigation-data"
   ```

4. 构建镜像、迁移数据库，再通过已挂载的 `/data` 传入一次性密码。密码文件在主机上由 UID/GID 10001 拥有且模式为 600，容器内路径由 `.env` 的 `NAV_INITIAL_PASSWORD_FILE=/data/.navigation-initial-password` 指定：

   ```bash
   set -euo pipefail
   source ./deploy/navigation-ops.sh
   DATA_DIR="$(resolve_data_dir)"
   require_data_marker "$DATA_DIR"
   docker compose build
   docker compose run --rm bookmark-navigation alembic upgrade head

   PASSWORD_FILE="$DATA_DIR/.navigation-initial-password"
   cleanup_password() {
     if sudo test -e "$PASSWORD_FILE"; then
       sudo shred --remove "$PASSWORD_FILE"
     fi
   }
   trap cleanup_password EXIT HUP INT TERM
   read -r -s -p '输入初始强密码: ' INITIAL_PASSWORD; printf '\n'
   printf '%s\n' "$INITIAL_PASSWORD" | sudo tee "$PASSWORD_FILE" >/dev/null
   unset INITIAL_PASSWORD
   sudo chown 10001:10001 "$PASSWORD_FILE"
   sudo chmod 600 "$PASSWORD_FILE"

   docker compose run --rm \
     bookmark-navigation python -m app.main create-user --username admin

   cleanup_password
   trap - EXIT HUP INT TERM
   docker compose up -d --wait
   NAV_PORT="$(resolve_nav_port)"
   curl --fail "http://127.0.0.1:${NAV_PORT}/healthz"
   ```

   `shred --remove` 会立即覆写并删除一次性文件；在 SSD/写时复制文件系统上不能保证物理扇区覆写，因此还应保护主机磁盘加密和管理员访问。无论命令成功、失败或被中断，trap 都会删除文件。

`create-user` 创建唯一主管理员，在数据库中已有用户时会拒绝继续，不会覆盖密码。初始化密码只用于首次登录，登录后必须立即改为至少 12 个字符且不等于用户名的新密码。后续普通账号由管理员在“用户管理”页面创建、启停、重置或永久删除；管理员不能浏览其他用户的书签内容。`/healthz` 无需登录，仅返回 `{"status":"ok"}`，不读取或泄露书签数据。

## HTTPS 反向代理

将 `deploy/nginx.conf.example` 复制到 Nginx 配置，替换域名和证书路径，检查后重载：

```sh
sudo nginx -t
sudo systemctl reload nginx
```

示例强制 HTTP 跳转 HTTPS，设置 HSTS、CSP、`nosniff`、Referrer-Policy 和 Permissions-Policy，并传递 `Host`、`X-Real-IP`、`X-Forwarded-For`、`X-Forwarded-Proto`。Nginx 会用 `$remote_addr` 覆写客户端 IP 头。Compose 将应用放在固定 Docker bridge：宿主机 Nginx 经发布端口连入时，应用看到的立即上游是 `NAV_DOCKER_GATEWAY=172.30.0.1`，因此 `NAV_TRUSTED_PROXY_IPS` 默认精确匹配该网关，不使用 `*`。如果 `172.30.0.0/24` 与现有网络发生 subnet conflict，必须一起修改 `NAV_DOCKER_SUBNET`、`NAV_DOCKER_GATEWAY`、`NAV_APP_IP` 和 `NAV_TRUSTED_PROXY_IPS`，并保证后三者位于新子网且地址不重复。只有在证书、DNS 和 HTTPS 端到端正常后才启用 HSTS。登录 Cookie 是 Secure/HttpOnly/SameSite=Strict，因此生产登录必须使用 HTTPS。

数据库恢复的会话屏障是进程内机制；生产必须保持 single Uvicorn worker（不要使用 `--workers` 或多副本共享 SQLite 数据目录）。

## 备份与恢复

应用会在导入、递归删除、永久删除用户和恢复前创建 SQLite 整库快照到 `/data/backups`。快照包含所有账号和用户数据，仅主管理员可查看和恢复。完整的主机卷备份必须在停服时进行，以便同时保存 SQLite 数据库、WAL/SHM 边车文件和快照：

```bash
set -euo pipefail
source ./deploy/navigation-ops.sh
DATA_DIR="$(resolve_data_dir)"
require_data_marker "$DATA_DIR"
BACKUP_FILE="$(require_outside_data_tree "$DATA_DIR" "$(pwd)/navigation-data-$(date +%Y%m%dT%H%M%S).tgz")"
docker compose stop bookmark-navigation
trap 'docker compose start bookmark-navigation' EXIT HUP INT TERM
sudo tar -C "$DATA_DIR" -czf "$BACKUP_FILE" .
sudo chown "$(id -u):$(id -g)" "$BACKUP_FILE"
docker compose start bookmark-navigation
trap - EXIT HUP INT TERM
printf 'Backup written to %s\n' "$BACKUP_FILE"
```

恢复完整卷时，归档路径可以是绝对路径或现有的相对路径；`readlink -f` 会先将它解析为规范绝对路径。下面命令会拒绝根路径或位于数据目录内的归档，并在替换前将当前卷写入 `${TMPDIR:-/tmp}` 下由 `mktemp` 创建的外部归档：

```bash
set -euo pipefail
source ./deploy/navigation-ops.sh
RESTORE_ARCHIVE=./navigation-data-YYYYmmddTHHMMSS.tgz
DATA_DIR="$(resolve_data_dir)"
require_data_marker "$DATA_DIR"
RESTORE_ARCHIVE="$(readlink -f -- "$RESTORE_ARCHIVE")"
[ -f "$RESTORE_ARCHIVE" ] || { echo 'restore archive not found' >&2; exit 1; }
RESTORE_ARCHIVE="$(require_outside_data_tree "$DATA_DIR" "$RESTORE_ARCHIVE")"
PRE_RESTORE="$(mktemp --tmpdir="${TMPDIR:-/tmp}" navigation-pre-restore-XXXXXXXX.tgz)"
PRE_RESTORE="$(require_outside_data_tree "$DATA_DIR" "$PRE_RESTORE")"

docker compose stop bookmark-navigation
sudo tar -C "$DATA_DIR" -czf "$PRE_RESTORE" .
sudo chown "$(id -u):$(id -g)" "$PRE_RESTORE"
sudo find "$DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
sudo tar -C "$DATA_DIR" -xzf "$RESTORE_ARCHIVE"
printf 'private-bookmark-navigation-data-v1\n' | sudo tee "$DATA_DIR/.bookmark-navigation-data" >/dev/null
sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR/backups"
sudo chown -R 10001:10001 "$DATA_DIR"
sudo chmod 700 "$DATA_DIR" "$DATA_DIR/backups"
sudo chmod 600 "$DATA_DIR/.bookmark-navigation-data"
docker compose start bookmark-navigation
NAV_PORT="$(resolve_nav_port)"
curl --fail "http://127.0.0.1:${NAV_PORT}/healthz"
```

恢复任一步骤失败时保持停服；不要让应用在部分恢复的卷上启动。根据错误修复数据目录，或用 `PRE_RESTORE` 归档重复恢复，完成所有权和模式检查后才手动启动。日常整库恢复可由主管理员在“导出与备份”页面完成；旧版快照会先迁移到当前 Alembic head，恢复前会再创建受保护快照，完成后注销全部用户会话。

## 升级和数据库迁移

1. 完成上述停服卷备份，记录当前 `NAV_IMAGE_TAG` 和 Git 提交。
2. 把 `.env` 中 `NAV_IMAGE_TAG` 改为不可变版本（例如 `2026-07-13`），然后：

   ```bash
   set -euo pipefail
   source ./deploy/navigation-ops.sh
   DATA_DIR="$(resolve_data_dir)"
   require_data_marker "$DATA_DIR"
   docker compose build --pull
   docker compose run --rm bookmark-navigation alembic upgrade head
   docker compose up -d --wait
   docker compose logs --tail=100 bookmark-navigation
   ```

迁移必须在新应用接受流量前运行。然后登录，验证搜索、编辑、导入、导出和退出。

## 回滚

代码回滚时将 `.env` 的 `NAV_IMAGE_TAG` 改回上一个已保留的镜像标签，然后验证专用数据目录标记再启动旧镜像：

```bash
set -euo pipefail
source ./deploy/navigation-ops.sh
DATA_DIR="$(resolve_data_dir)"
require_data_marker "$DATA_DIR"
docker compose up -d --wait --no-build
```

如升级执行了不向后兼容的迁移，不要只降级代码；停服后按上述完整卷恢复流程恢复升级前归档，然后用旧镜像启动。保留失败升级的卷副本，便于排查和再次前向迁移。

## 手动导入与导出

- 导入：从浏览器导出 Netscape 书签 HTML，在“数据 → 导入书签”中先预览。逐项确认冲突覆盖开关后才应用；默认不覆盖，也不因导入文件缺少项而删除服务器书签。
- 导出：“导出与备份”页面可下载当前登录用户的浏览器 HTML 或完整 JSON；两种格式都不会包含其他用户数据。
- 警告：多数浏览器导入 HTML 时会“追加”而非“替换”现有书签，反复导入可能产生重复项。在浏览器中手动导入前先导出浏览器自身备份，并在小范围验证。JSON 不是浏览器书签导入格式。

## 运维检查

```bash
set -euo pipefail
source ./deploy/navigation-ops.sh
DATA_DIR="$(resolve_data_dir)"
require_data_marker "$DATA_DIR"
docker compose ps
docker compose logs --tail=100 bookmark-navigation
NAV_PORT="$(resolve_nav_port)"
curl --fail "http://127.0.0.1:${NAV_PORT}/healthz"
curl --fail https://bookmarks.example.com/healthz
docker compose config
```

停止服务使用 `docker compose down`；该命令不带 `--volumes`，bind mount 中的 `data/` 会保留。不要使用 `docker compose down --volumes` 或手动删除 `NAV_DATA_DIR`。
