# Bookmark Navigation 本地开发环境设计

## 目标

使用当前本机工具重新构建可复现的本地开发环境，不复用迁移前复制或历史构建产生的 Python、Node.js 环境。

## 版本与工具

- Python 固定为 `3.13.14`，由 `uv 0.11.30` 选择和管理。
- Node.js 固定为 `v24.18.0`，由 `fnm 1.39.0` 选择和管理。
- 后端依赖以 `navigation/backend/pyproject.toml` 为声明源，由 `uv.lock` 锁定。
- 前端依赖以 `navigation/frontend/package-lock.json` 为锁定源，由 `npm ci` 安装。

## 文件与目录

- 根目录 `.python-version` 固定 Python 解释器版本。
- 根目录 `.node-version` 固定 Node.js 版本。
- `navigation/backend/.venv/` 是由 uv 新建的本地环境，继续由根级 `.gitignore` 忽略。
- `navigation/backend/uv.lock` 是可复现依赖锁文件，应作为项目文件保留。
- `navigation/frontend/node_modules/` 是由 npm 新建的本地依赖目录，继续由根级 `.gitignore` 忽略。

## 初始化流程

1. 删除目标目录内现存的 `.venv`、`venv`、`node_modules`、`dist`、Python/pytest 缓存、egg-info、Playwright 输出和 TypeScript 构建缓存。
2. 在后端目录执行 `uv sync --python 3.13.14 --extra test`。
3. 在前端目录通过 `fnm exec --using` 读取根级 `.node-version`，执行 `npm ci`。
4. 运行后端完整测试，以及前端单元测试、类型检查和生产构建。

## Python 3.13 验证说明

后端在 Python 3.13.14 下以全局 `-W error` 运行完整测试。初始化时发现的 SQLite 连接回收 `ResourceWarning` 已按 [SQLite 连接生命周期修复设计](2026-07-21-sqlite-connection-lifecycle-design.md) 处理；当前门禁不添加警告过滤器。

## 边界

- 不初始化 Git，不提交，不配置远程仓库。
- 不复制原知识库中的私人书签、数据库、备份、环境变量或离线包。
- 不安装 Playwright 浏览器，不启动 Docker 或生产服务。
