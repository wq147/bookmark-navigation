# Linux 服务器历史部署记录（2026-07-14）

本文是经过公开脱敏的**历史部署记录**，保留 2026-07-14 首次上传源码、构建镜像和启动服务的流程，但主机、账号、密钥名、校验值和家目录均替换为示例。它用于追溯当时操作顺序，不是其他服务器的推荐安装手册。通用备份、恢复、升级和回滚要求仍以项目根目录的 `README_FIRST.md` 导航到的当前权威手册为准。

> 后续在其他 `linux/amd64` 服务器部署时，可直接使用已构建镜像的离线安装包，无需再上传源码或现场构建。制作和使用步骤见 [`release/docs/DEPLOYMENT.md`](../release/docs/DEPLOYMENT.md)。

## 示例化部署状态

| 项目 | 脱敏示例值 |
| --- | --- |
| SSH 用户 | `deploy` |
| 部署目录 | `/opt/bookmark-navigation/navigation` |
| 数据目录 | `/opt/bookmark-navigation/data` |
| Compose 服务 | `bookmark-navigation` |
| 镜像 | `bookmark-navigation:2026-07-14-r2` |
| 容器网络 | `navigation_navigation` |
| 容器地址 | `172.30.0.2` |
| 宿主机端口 | `127.0.0.1:8080` |
| 初始用户名 | `admin` |
| 初始密码暂存文件 | `/home/deploy/bookmark-navigation-initial-password.txt` |

已验证容器 `healthy`，`/healthz` 返回 200，未登录访问 `/` 返回 303 并跳转 `/login`，登录页和静态资源返回 200，真实密码登录 API 返回 200 并生成 CSRF 令牌。

## 1. 上传和校验部署包

在本地执行：

```bash
scp -i ~/.ssh/id_ed25519_bookmark_example \
  bookmark-navigation-deploy-20260714-r2.tar.gz \
  deploy@bookmark.example:/home/deploy/
```

在服务器校验：

```bash
echo '<REPLACE_WITH_SHA256>  /home/deploy/bookmark-navigation-deploy-20260714-r2.tar.gz' \
  | sha256sum --check --strict
```

## 2. 解压源码

```bash
sudo install -d -o root -g root -m 755 /opt/bookmark-navigation
sudo tar --no-same-owner \
  -xzf /home/deploy/bookmark-navigation-deploy-20260714-r2.tar.gz \
  -C /opt/bookmark-navigation
```

Linux `tar` 如果提示忽略 `LIBARCHIVE.xattr.com.apple.provenance`，只是忽略 macOS 扩展属性，不影响文件内容。

## 3. 生成生产配置

```bash
cd /opt/bookmark-navigation/navigation
sudo cp .env.example .env
sudo sed -i 's|^NAV_DATA_DIR=.*|NAV_DATA_DIR=/opt/bookmark-navigation/data|' .env
sudo sed -i 's|^NAV_IMAGE_TAG=.*|NAV_IMAGE_TAG=2026-07-14-r2|' .env
sudo sed -i 's|^NAV_BIND_ADDRESS=.*|NAV_BIND_ADDRESS=127.0.0.1|' .env
sudo chown root:root .env
sudo chmod 600 .env
sudo docker compose config --quiet
```

默认网段为 `172.30.0.0/24`，网关为 `172.30.0.1`，应用地址为 `172.30.0.2`。部署前应先检查它与已有 Docker 网络不冲突：

```bash
sudo docker network inspect $(sudo docker network ls -q) \
  --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{.Gateway}}{{end}}'
```

如果冲突，必须同时修改 `NAV_DOCKER_SUBNET`、`NAV_DOCKER_GATEWAY`、`NAV_APP_IP` 和 `NAV_TRUSTED_PROXY_IPS`。

## 4. 初始化数据目录

```bash
DATA_DIR=/opt/bookmark-navigation/data
sudo test ! -e "$DATA_DIR"
sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR"
printf 'private-bookmark-navigation-data-v1\n' \
  | sudo tee "$DATA_DIR/.bookmark-navigation-data" >/dev/null
sudo install -d -o 10001 -g 10001 -m 700 "$DATA_DIR/backups"
sudo chown -R 10001:10001 "$DATA_DIR"
sudo chmod 700 "$DATA_DIR" "$DATA_DIR/backups"
sudo chmod 600 "$DATA_DIR/.bookmark-navigation-data"
```

`10001` 是容器内非 root 应用用户的固定 UID。宿主机数据目录以 `10001:10001` 和模式 `700` 初始化，实际数据库文件可能显示为 `10001:999`，其中 `999` 是基础镜像分配的容器主组 GID。访问控制依靠所有者 UID 和父目录的 `700` 权限，不要把数据目录改成普通宿主机用户所有。

## 5. 生成初始密码

```bash
CREDENTIAL_FILE=/home/deploy/bookmark-navigation-initial-password.txt
umask 077
openssl rand -base64 24 > "$CREDENTIAL_FILE"
chmod 600 "$CREDENTIAL_FILE"
sudo install -o 10001 -g 10001 -m 600 \
  "$CREDENTIAL_FILE" \
  /opt/bookmark-navigation/data/.navigation-initial-password
```

家目录副本仅用于把密码交付给用户，不会挂载进容器。用户把密码保存到密码管理器后应立即删除该文件。

## 6. 构建、迁移和创建用户

```bash
cd /opt/bookmark-navigation/navigation
sudo docker compose build
sudo docker compose run --rm bookmark-navigation alembic upgrade head
sudo docker compose run --rm \
  bookmark-navigation python -m app.main create-user --username admin
sudo shred --remove /opt/bookmark-navigation/data/.navigation-initial-password
```

`create-user` 是一次性命令；数据库已有用户时会拒绝覆盖。

## 7. 启动和验收

```bash
cd /opt/bookmark-navigation/navigation
sudo docker compose up -d --wait
sudo docker compose ps
sudo docker compose logs --tail=100 bookmark-navigation
curl --fail http://127.0.0.1:8080/healthz
curl --silent --show-error --dump-header - --output /dev/null \
  http://127.0.0.1:8080/
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8080/login
```

预期结果：

- `docker compose ps` 显示 `healthy`；
- `/healthz` 返回 `{"status":"ok"}`；
- `/` 返回 303，`Location: /login`；
- `/login` 返回 200。

## 8. 反向代理

当前宿主机只监听 `127.0.0.1:8080`。如果 Nginx/OpenResty 直接运行在宿主机网络中，代理目标为：

```text
http://127.0.0.1:8080
```

至少传递：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

如果反向代理也在普通 Docker bridge 容器中，它无法访问宿主机的 `127.0.0.1`。此时应让反代加入应用网络直连服务，或将发布地址调整为反代可达的宿主机地址并配置防火墙。

登录 Cookie 启用 `Secure`，正式登录必须通过 HTTPS。

## 9. 领取密码和日常运维

读取初始密码：

```bash
cat /home/deploy/bookmark-navigation-initial-password.txt
```

保存到密码管理器后：

```bash
shred --remove /home/deploy/bookmark-navigation-initial-password.txt
```

日常检查：

```bash
cd /opt/bookmark-navigation/navigation
sudo docker compose ps
sudo docker compose logs --tail=100 bookmark-navigation
curl --fail http://127.0.0.1:8080/healthz
```

停止应用但保留数据：

```bash
cd /opt/bookmark-navigation/navigation
sudo docker compose down
```

不要执行 `docker compose down --volumes`，不要手动删除 `/opt/bookmark-navigation/data`。
