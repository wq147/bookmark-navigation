# Bookmark Navigation 离线部署指南

本安装包包含已构建的 Docker 镜像，仅支持 `linux/amd64`。目标服务器无需安装 Node.js、Python，也无需访问镜像仓库。

## 安装包文件作用

| 包内文件 | 作用 |
| --- | --- |
| `install.sh` | 校验平台和包完整性、导入镜像、首次初始化或原地升级、升级前备份数据库、启动后健康检查 |
| `compose.yaml` | 目标服务器的运行时 Compose，只引用已加载镜像，不包含 `build:` |
| `image/bookmark-navigation-amd64.tar` | `docker load` 导入的 Linux amd64 应用镜像归档 |
| `config/bookmark_policy.json` | 首次安装时的默认分类策略；升级时不会静默覆盖用户已修改的策略 |
| `VERSION` | 离线包版本，同时用于生成版本化解压目录 |
| `MANIFEST` | 记录支持平台、镜像仓库名、镜像标签和镜像归档路径 |
| `SHA256SUMS` | 安装器使用的包内文件 SHA-256 完整性校验清单 |
| `docs/DEPLOYMENT.md` | 随包交付的首装、升级、改端口、反代、备份、运维和排错手册，即本文 |

## 前置条件

- Linux `x86_64/amd64`。
- Docker Engine 可用。
- Docker Compose v2，即 `docker compose version` 可执行。
- `sudo`、`ss`、`curl`、`sha256sum`、`tar` 等常见 Linux 命令。
- 安装命令需要 root 权限。

安装器不会自动安装 Docker，也不会修改系统软件源。

## 首次安装

1. 上传并解压安装包：

   ```bash
   tar -xzf bookmark-navigation-offline-amd64-<VERSION>.tar.gz
   cd bookmark-navigation-offline-amd64-<VERSION>
   ```

2. 交互安装。脚本会隐藏输入并二次确认初始管理员密码：

   ```bash
   sudo ./install.sh --listen 127.0.0.1 --port 8080
   ```

   默认管理员用户名为 `admin`。可在首次安装时修改：

   ```bash
   sudo ./install.sh \
     --listen 127.0.0.1 \
     --port 8080 \
     --username admin
   ```

3. 自动化或无 TTY 环境使用权限为 `600` 的密码文件：

   ```bash
   sudo chmod 600 /root/bookmark-navigation-password
   sudo ./install.sh \
     --listen 127.0.0.1 \
     --port 8080 \
     --password-file /root/bookmark-navigation-password \
     --yes
   ```

   安装器不支持在命令行中直接携带密码，也不会将密码写入 `.env`、安装状态或日志。

4. 首次登录会强制主管理员修改上述临时密码。新密码至少 12 个字符且不能与用户名相同。普通用户由主管理员登录后在“用户管理”页面创建，并各自拥有完全隔离的文件夹、书签、搜索、导入和导出数据。

## 自定义目录

默认安装目录为 `/opt/bookmark-navigation`，数据目录为 `/opt/bookmark-navigation/data`。可以分开指定：

```bash
sudo ./install.sh \
  --install-dir /opt/bookmark-navigation \
  --data-dir /srv/bookmark-navigation-data \
  --listen 127.0.0.1 \
  --port 8080
```

数据目录包含 SQLite 数据库和备份，不要手动删除。安装器会用数据标记防止对错误目录执行递归权限修改。

## 监听地址与端口

推荐让同机 Nginx/OpenResty 代理回环地址：

```bash
sudo ./install.sh --listen 127.0.0.1 --port 8080
```

如需从宿主机外部直接访问，可显式绑定所有 IPv4 网卡：

```bash
sudo ./install.sh --listen 0.0.0.0 --port 18080
```

`0.0.0.0` 会将端口暴露到服务器可达网络，应同时配置云安全组或主机防火墙。正式登录应通过 HTTPS。

## 原地升级

将新版离线包上传、解压，然后再次指向原安装目录：

```bash
cd bookmark-navigation-offline-amd64-<NEW_VERSION>
sudo ./install.sh --install-dir /opt/bookmark-navigation --yes
```

升级会：

- 保留已有账号、密码和书签数据；
- 将 v0.1.x 最早创建的账号设为唯一主管理员，并把旧书签、文件夹、导入和操作记录归属该账号；
- 保留已有监听地址和端口，除非新命令显式传入；
- 停止应用后备份 SQLite 数据库；
- 加载新镜像、执行 Alembic 迁移并重建容器；
- 不覆盖已修改的 `bookmark_policy.json`，新包版本会保存为 `bookmark_policy.json.package-new`。

升级时不需要再次提供密码。`--username` 和 `--password-file` 不会重置已有账号。

升级同时修改端口：

```bash
sudo ./install.sh \
  --install-dir /opt/bookmark-navigation \
  --listen 127.0.0.1 \
  --port 18080 \
  --yes
```

## 备份

默认升级备份位于：

```text
/opt/bookmark-navigation/data/backups/pre-upgrade-<UTC时间>-<PID>.db
```

如使用了 `--data-dir`，则在该数据目录的 `backups/` 下。数据库迁移失败时，新服务不会启动，脚本会显示本次备份路径。

应用内 SQLite 快照是包含全部用户的整库备份，仅主管理员可查看和恢复。恢复会影响所有账号和数据；界面要求明确确认，恢复前保存受保护快照，旧版快照先升级到当前数据库版本，恢复完成后注销全部会话。

## 反向代理

回环绑定时，宿主机 Nginx 代理目标为 `http://127.0.0.1:8080`。至少传递：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

如果反向代理运行在另一个 Docker bridge 容器中，它无法访问宿主机的 `127.0.0.1`。此时需将发布地址调整为反代容器可达的宿主机地址，或手动把反代加入应用网络。

## 日常运维

安装器使用与安装目录绑定的 Compose 项目名。以默认目录为例：

```bash
cd /opt/bookmark-navigation
PROJECT_NAME="$(awk -F= '$1 == "project_name" {print $2}' install-state)"
sudo docker compose -p "$PROJECT_NAME" --env-file .env -f compose.yaml ps
sudo docker compose -p "$PROJECT_NAME" --env-file .env -f compose.yaml \
  logs --tail 100 bookmark-navigation
curl --fail http://127.0.0.1:8080/healthz
```

停止或启动：

```bash
sudo docker compose -p "$PROJECT_NAME" --env-file .env -f compose.yaml \
  stop bookmark-navigation
sudo docker compose -p "$PROJECT_NAME" --env-file .env -f compose.yaml \
  up -d --wait
```

不要删除数据目录，也不要对不明确路径执行递归 `rm`/`chown`。

## 常见错误

- `requires Linux amd64`：服务器不是 Linux x86_64。
- `Docker Engine is unavailable`：启动 Docker，并确认 root 可执行 `docker info`。
- `Docker Compose v2 is unavailable`：安装 Compose v2 插件。
- `checksum verification failed`：安装包不完整或被修改，应重新上传原包。
- `port ... is already in use`：改用未占用端口，或先确认占用服务是否可停止。
- `non-empty ... without valid install-state`：目标不是安装器创建的可管理目录，脚本为避免覆盖而拒绝继续。

## 制作新离线包

仅在持有已构建镜像的发布服务器上执行：

```bash
cd navigation
sudo ./release/build-offline-bundle.sh \
  --image bookmark-navigation:0.2.0 \
  --version 2026.07.15-r1 \
  --output-dir /opt/bookmark-navigation/releases
```

构建器会验证镜像为 `linux/amd64`，执行 `docker save`，生成内部 `SHA256SUMS`，并输出最终 `tar.gz` 的 SHA-256。
