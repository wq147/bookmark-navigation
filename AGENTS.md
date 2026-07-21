# Bookmark Navigation Agent 指南

## 项目目标与当前阶段

本项目包含两部分：根目录的 Netscape HTML 书签整理工具链，以及 `navigation/` 下的 FastAPI + Vue 私人导航页。当前阶段是独立源码目录的本地开发环境与文档一致性维护；目录尚未初始化 Git，GitHub 发布、生产部署和源知识库修改均不在默认范围内。

`README_FIRST.md` 是项目唯一主入口。当前源码不包含私人 V5 HTML、数据库、备份、`.env` 或离线 `tar.gz`；不要从原知识库复制这些内容来补齐测试。

## 架构与数据流

- `bookmark_policy.json`：分类规则的机器可读唯一真源；`BOOKMARK_RULES.md` 是面向人的说明。
- `bookmark_organizer.py`、`bookmark_numbering.py`、`bookmark_audit.py`：生成新 HTML、规范编号和独立审计；默认不得覆盖真实输入。
- `navigation/backend/app/`：FastAPI 路由、认证、书签领域服务、导入预览/应用、导出与整库备份恢复。
- `navigation/backend/alembic/`：SQLite 迁移；迁移文件是正式项目文件，不得为通过测试而改写历史版本。
- `navigation/frontend/src/`：Vue 3、Pinia、Vue Router 三栏工作台和管理界面；开发代理把 `/api` 转到 `127.0.0.1:8000`。
- `navigation/compose.yaml` 与 `navigation/Dockerfile`：源码构建模式；`navigation/release/` 是无 `build:` 的离线交付模式，两者不可混用。
- 主要数据流为：浏览器 HTML -> 导入预览 -> 用户确认应用 -> SQLite；导出时从当前用户隔离数据生成 HTML/JSON。破坏性操作前创建整库快照。

## 环境、依赖与命令

- Python `3.13.14` 由根目录 `.python-version` 固定，使用 `uv 0.11.30`；依赖声明与锁文件分别是 `navigation/backend/pyproject.toml` 和 `uv.lock`。
- Node.js `v24.18.0` 由根目录 `.node-version` 固定，使用 `fnm 1.39.0`；前端必须保留并使用 `package-lock.json`。
- 后端初始化与测试（在 `navigation/backend`）：
  `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --extra test`，随后运行 `UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -W error -m pytest -q`。
- 前端初始化与验证（在 `navigation/frontend`）：
  `fnm exec --using ../../.node-version npm ci`，随后依次运行 `npm test -- --run`、`npm run typecheck`、`npm run build`，每条命令均通过同一 `fnm exec --using ../../.node-version` 上下文执行。
- Shell 脚本按 shebang 使用 `bash -n` 验证：`navigation/deploy/navigation-ops.sh`、`navigation/release/install.sh`、`navigation/release/build-offline-bundle.sh`。
- Docker 可用时，从 `navigation/` 运行 `docker compose config`；不得在本地整理任务中启动或修改生产服务与数据。

## 修改规则与安全边界

- 修改前先读 `README_FIRST.md`、相关源码/测试、`git status`（若未来成为仓库）以及对应配置；以实际代码和锁文件为准，不把历史计划当成当前实现。
- 修改后运行受影响的定向测试，再运行完整后端测试、前端单元测试、类型检查和构建；文档路径与相对链接也必须复核。
- 环境变量以 `navigation/.env.example`、Compose 和代码读取结果交叉核对。不得提交真实 `.env`、密码、Token、私钥、SQLite 数据、备份或私人书签。
- 生产默认只绑定 `127.0.0.1`，通过 HTTPS 反向代理访问；不要放宽可信代理为 `*`，不要启用多 Uvicorn worker 共享同一 SQLite 数据目录。
- 不执行 `docker compose down --volumes`，不删除用途不明文件，不重置工作区，不修改 Git 历史，不升级主要依赖，不擅自初始化 Git、发布或部署。
- `.venv/`、`node_modules/`、`dist/`、缓存和测试输出是本地生成物，应由 `.gitignore` 排除；锁文件、迁移、示例配置和发布脚本必须保留。

## 当前技术债与下一步

- SQLite 原生连接和测试 engine 已改为确定性释放；保持 Python 3.13 全局 `-W error` 作为资源生命周期回归门禁。
- Playwright E2E 与 Docker Compose/镜像/健康检查需要具备浏览器和 Docker 的环境复验，不能沿用历史结果冒充当前通过。
- 当前目录没有 Git 分支或提交基线。若进入 GitHub 发布阶段，先做公开内容与敏感信息审计，再由用户明确授权初始化、提交和远程操作。
