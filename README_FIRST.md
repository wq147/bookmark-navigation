# 书签管理与私人导航页

本文是 Bookmark Navigation 项目的**唯一主入口**。这个目录同时包含两类能力：

- 书签整理工具链：分类、编号、去重、审计和 Netscape HTML 输出。
- 私人导航页：带多用户账号隔离和唯一主管理员的 FastAPI + Vue 应用，支持手动导入、编辑、搜索、备份和导出浏览器书签 HTML。

GitHub 项目概览见 [`README.md`](README.md)，漏洞报告方式见 [`SECURITY.md`](SECURITY.md)，项目采用 [`AGPL-3.0-only`](LICENSE) 许可证。

## 按使用场景开始

### 直接使用

导航页已部署时，直接在浏览器打开你配置的 HTTPS 域名。日常书签修改在导航页完成；需要回到浏览器时，从导航页导出 Netscape HTML，再手动导入浏览器。

### 新服务器部署

普通 Linux `amd64/x86_64` 服务器首选离线安装包，不需要上传源码或现场构建镜像。`2026.07.15-r1` 已完成 Linux amd64 首装、管理员初始化和端口变更验收；完整参数和升级方法见 [离线部署指南](navigation/release/docs/DEPLOYMENT.md)。离线包是单独发布的二进制交付物，不位于、也不纳入当前独立源码目录。

```bash
tar -xzf bookmark-navigation-offline-amd64-2026.07.15-r1.tar.gz
cd bookmark-navigation-offline-amd64-2026.07.15-r1
sudo ./install.sh --listen 127.0.0.1 --port 8080
```

如需绑定所有 IPv4 网卡，显式使用 `--listen 0.0.0.0`，并同时配置防火墙、反向代理和 HTTPS。

### 日常整理

开始前阅读 [书签分类规则](BOOKMARK_RULES.md)。分类规则变更时，先修改 `bookmark_policy.json`，再运行整理和审计脚本；对真实书签保持“先预览/生成新文件，后人工确认”。

### 开发维护

修改后端、前端、Docker 镜像，或需要手工备份/回滚时，阅读 [`navigation/README.md`](navigation/README.md)。该文档包含当前 uv/fnm 本地环境、测试和构建命令，是源码构建与高级运维说明，不是新服务器普通安装的首选入口。

## 顶层文件作用

| 文件                                                       | 作用                             | 使用注意                |
| -------------------------------------------------------- | ------------------------------ | ------------------- |
| `README_FIRST.md`                                        | 整个书签项目的唯一主入口                   | 先从本文选择场景，再进入专业文档    |
| `BOOKMARK_RULES.md`                                      | 人类可读的分类、命名、编号、去重和安全规则          | 规则说明，不是脚本直接读取的配置    |
| `bookmark_policy.json`                                   | 分类和路径规则的机器可读唯一真源               | 分类体系变更时优先修改它        |
| `bookmark_organizer.py`                                  | 按策略整理 Netscape HTML，并生成变更/组织报告 | 默认输出新文件，不覆盖源文件      |
| `bookmark_numbering.py`                                  | 仅规范文件夹编号                       | 不重新分类书签             |
| `bookmark_audit.py`                                      | 审计重复 URL、编号、空文件夹、过大目录和分类异常     | 用于整理后的独立校验          |
| `.python-version`                                        | uv 使用的本地 Python 版本固定文件          | 当前为 `3.13.14`       |
| `.node-version`                                          | fnm 使用的本地 Node.js 版本固定文件        | 当前为 `v24.18.0`      |
| `navigation/`                                            | 私人导航页源码、测试、运维和离线发布工具           | 目录职责见下表             |

## `navigation/` 目录作用

| 路径 | 作用 |
| --- | --- |
| `navigation/backend/` | FastAPI、SQLite/Alembic、账号认证、导入导出、备份与后端测试 |
| `navigation/frontend/` | Vue 3 三栏工作台、编辑、搜索、导入预览、备份界面与前端测试 |
| `navigation/deploy/` | 源码 Compose 模式下的安全运维守卫和 Nginx 示例 |
| `navigation/release/` | 离线发布 Compose、一键安装器、打包脚本、版本和随包文档 |
| `navigation/docs/` | 验收记录、历史部署记录、设计决策和实施计划 |

## 文档导航

| 文档 | 适用场景 |
| --- | --- |
| [书签分类规则](BOOKMARK_RULES.md) | 调整分类、标题、编号或安全约束 |
| [离线部署指南](navigation/release/docs/DEPLOYMENT.md) | 新服务器首装、原地升级、改端口、反代、备份和排错 |
| [源码构建与高级运维](navigation/README.md) | 修改代码、重新构建镜像、手工备份/恢复/回滚 |
| [Agent 项目约束](AGENTS.md) | 后续 Codex/Agent 会话的架构、边界、命令和当前重点 |
| [2026-07-13 验收记录](navigation/docs/acceptance-2026-07-13.md) | 查看功能、安全、迁移和脱敏验收方法 |
| [2026-07-14 历史部署记录](navigation/docs/linux-server-deployment-2026-07-14.md) | 回看首次源码部署的脱敏流程，不作为新部署首选手册 |
| [产品、安全和发布设计决策的开发历史](navigation/docs/superpowers/specs/README.md) | 汇总产品范围、安全边界、离线发布和文档结构设计 |
| [实施步骤与验收任务分解的开发历史](navigation/docs/superpowers/plans/README.md) | 汇总应用、离线安装器和文档整理的历史实施计划 |

## 书签整理工作流

1. 从浏览器或导航页导出 Netscape HTML。
2. 复制为新的输入/工作文件，不覆盖上一个已验收版本。
3. 确认 `BOOKMARK_RULES.md` 与 `bookmark_policy.json` 的规则符合当前需求。
4. 运行 `bookmark_organizer.py`，检查生成的变更报告和新 HTML。
5. 如果只需重排文件夹编号，使用 `bookmark_numbering.py`，不必重跑全量分类。
6. 运行 `bookmark_audit.py` 做独立审计，确认重复 URL、泛化目录、空目录异常和编号异常为可接受值。
7. 人工确认后再导入导航页或浏览器。缺少的 URL 默认不代表删除。

具体命令和参数见 [书签分类规则](BOOKMARK_RULES.md)中的“自动整理命令”和“审计命令”。

## 当前源码目录边界

- 当前目录包含书签规则与整理脚本、私人导航页源码、测试、部署脚本和离线包构建工具。
- 私人验收样本含个人数据，不纳入当前独立源码目录；如需本地回归，通过 `NAV_PRIVATE_BOOKMARK_FIXTURE` 指向仓库外的 Netscape Bookmark HTML，未配置时相关测试明确跳过。
- `bookmark-navigation-offline-amd64-2026.07.15-r1.tar.gz` 是单独发布的二进制交付物，不纳入当前独立源码目录；发布包的 SHA-256 应以该次交付随附的校验文件为准。
- `.venv/`、`node_modules/`、`dist/` 和测试缓存是可再生成的本地文件，受 `.gitignore` 保护，不是源码交付物。

## 安全与维护约束

- `bookmark_policy.json` 是分类真源，不在其他文档再维护一套冲突策略。
- 大规模导入保持“先预览，后应用”；不因新 HTML 缺少某个 URL 而自动删除数据库书签。
- 不把私人 HTML 样本、密码、`.env`、SQLite 数据库或备份复制进公开源码或提交到 Git。
- 离线 `tar.gz` 是单独管理的二进制交付物，不纳入源码 Git 仓库。
