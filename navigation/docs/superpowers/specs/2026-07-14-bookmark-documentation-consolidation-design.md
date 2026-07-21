# 书签管理项目文档整理设计

- 日期：2026-07-14
- 状态：已确认，待实施
- 范围：仅整理本地 `30-资源/工具/书签管理`

## 1. 目标

将 `README_FIRST.md` 设为整个书签管理项目的唯一主入口，让新读者无需先理解项目历史，即可判断：

- 平时使用个人导航页应读哪份文档；
- 在新 Linux 服务器部署应使用哪个安装包和命令；
- 开发、重建镜像和高级运维应阅读哪份文档；
- 书签整理、编号、审计脚本和分类规则分别负责什么；
- 哪些文件是正式交付物，哪些只是历史记录或开发过程资料。

## 2. 文档层级

### 2.1 唯一主入口

`30-资源/工具/书签管理/README_FIRST.md` 是唯一全局入口，承担以下职责：

1. 简述书签管理工作区与私人导航页的关系。
2. 按“直接使用”、“新服务器部署”、“日常整理”、“开发维护”四种场景给出最短路径。
3. 用文件职责表说明顶层脚本、规则、HTML 源数据、报告、`navigation/` 应用和离线包的用途。
4. 提供各专业文档的链接，但不复制其全部操作细节。

### 2.2 专业文档

| 文档 | 职责 | 是否主入口 |
| --- | --- | --- |
| `README_FIRST.md` | 全局导航、场景选择、顶层文件职责 | 是 |
| `BOOKMARK_RULES.md` | 分类、命名、编号、去重和安全规则 | 否 |
| `navigation/release/docs/DEPLOYMENT.md` | 离线包首装、升级、端口、反代、备份和故障排查 | 否 |
| `navigation/README.md` | 源码构建、开发环境、手工运维和回滚 | 否 |
| `navigation/docs/linux-server-deployment-2026-07-14.md` | 2026-07-14 首次真实服务器源码部署记录 | 否，历史记录 |
| `navigation/docs/acceptance-2026-07-13.md` | 功能、迁移、真实 V5 数据和安全验收证据 | 否，验收记录 |
| `navigation/docs/*design*.md` | 已确认的产品与部署设计决策 | 否，开发历史 |
| `navigation/docs/*plan*.md` | 实施步骤和验收任务分解 | 否，开发历史 |

## 3. 文件职责说明

### 3.1 顶层书签工作区

`README_FIRST.md` 至少要解释以下文件或文件类型：

- `bookmark_policy.json`：分类与路径规则的机器可读唯一真源。
- `BOOKMARK_RULES.md`：人类可读的分类、命名、编号和维护原则。
- `bookmark_organizer.py`：按策略整理书签并生成变更报告。
- `bookmark_numbering.py`：仅处理文件夹编号规范。
- `bookmark_audit.py`：对重复、编号、空文件夹和分类异常进行审计。
- 仓库外私人 fixture：用于本地验收的 Netscape HTML 书签数据样本，不进入公开源码。
- `bookmarks_personalized_v5_*report*` 和 `*verify*`：V5 整理、审计、变更和最终校验记录，不是程序输入真源。
- `navigation/`：私人导航页应用源码、测试、开发部署和离线发布工具。
- `bookmark-navigation-offline-amd64-2026.07.14-r2.tar.gz`：当前最终 Linux amd64 离线交付包，不纳入 Git。

### 3.2 `navigation/` 应用目录

`navigation/README.md` 至少要解释：

- `backend/`：FastAPI、SQLite/Alembic、认证、导入导出、备份和后端测试。
- `frontend/`：Vue 3 三栏工作台、导入预览、编辑、备份界面和前端测试。
- `Dockerfile`：构建前端静态文件与 Python 运行镜像的多阶段构建。
- `compose.yaml`：源码构建和开发/手工部署使用，包含 `build:`。
- `.env.example`：源码 Compose 模式的环境变量模板。
- `deploy/`：源码模式的安全运维守卫和 Nginx 反代示例。
- `release/`：无 `build:` 的运行 Compose、一键安装器、离线包构建器、版本与发布清单。
- `docs/`：验收证据、真实部署记录、设计和实施计划。

### 3.3 离线包内容

`navigation/release/docs/DEPLOYMENT.md` 要增加安装包文件职责表：

| 包内文件 | 职责 |
| --- | --- |
| `install.sh` | 校验包、导入镜像、初始化或升级应用、备份数据库和健康检查 |
| `compose.yaml` | 目标机运行时 Compose，只引用已加载镜像，不现场构建 |
| `image/bookmark-navigation-amd64.tar` | `docker load` 使用的 Linux amd64 镜像归档 |
| `config/bookmark_policy.json` | 首次安装使用的分类策略；升级不静默覆盖用户修改 |
| `VERSION` | 离线包版本 |
| `MANIFEST` | 平台、镜像名、镜像标签和镜像归档路径 |
| `SHA256SUMS` | 包内文件完整性校验 |
| `docs/DEPLOYMENT.md` | 随包交付的安装、升级与运维手册 |

## 4. 内容去重与表述规则

- 离线包是在其他 Linux amd64 服务器上部署的默认方式。
- 上传源码、设置 `.env`、执行 `docker compose build` 只属于开发或重新构建镜像流程。
- `navigation/docs/linux-server-deployment-2026-07-14.md` 显式标注为“历史部署记录”，不作为新服务器的推荐手册。
- 主入口给出最少必需命令，完整参数、备份、反代和故障处理链接到专业文档。
- 文档使用中文说明，保留真实文件名、参数名和命令行。

## 5. 清理边界

删除已被最终离线包替代的旧调试包：

- `bookmark-navigation-deploy-20260714.tar.gz`
- `bookmark-navigation-deploy-20260714-r2.tar.gz`

保留：

- `bookmark-navigation-offline-amd64-2026.07.14-r2.tar.gz`
- 与书签项目无关的 `00-收件箱/Ubuntu_SSH密钥登录与NOPASSWD_sudo安全配置_SOP.md`

最终离线包是二进制交付物，保持未跟踪，不提交到 Git。

服务器不在本次整理范围内：不登录服务器，不删除服务器文件，不调整正式应用、容器或数据。

## 6. 验证与验收

文档整理完成后必须验证：

1. `README_FIRST.md` 包含顶层工具、应用目录、主要文档和最终离线包的职责说明。
2. `navigation/README.md` 明确它是源码构建与高级运维文档，并解释应用各目录职责。
3. `release/docs/DEPLOYMENT.md` 包含包内全部八类文件的职责。
4. 所有 Markdown 相对链接指向存在的目标。
5. 现有部署文档测试和后端全量测试仍通过。
6. 两个旧调试包不再存在，最终离线包的 SHA-256 仍为 `0ca915514747416311ee40948750523d45931fe6df9a4f4468d7af0c6974dc7f`。

## 7. Git 范围

本次 Git 提交只包含：

- 文档整理与文件职责说明；
- 针对文档结构和必需说明的自动化测试；
- 本设计与后续实施计划。

不包含：

- 最终 `tar.gz` 离线包；
- 与书签项目无关的未跟踪文件；
- 应用业务代码修改。
