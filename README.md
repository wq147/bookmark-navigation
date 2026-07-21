# Bookmark Navigation

Bookmark Navigation 是一个可独立运行的书签整理与私人导航项目，包含：

- Netscape Bookmark HTML 的分类、编号、去重与审计工具链。
- `navigation/` 下基于 FastAPI、SQLite 和 Vue 3 的多用户导航页，支持导入预览、编辑、搜索、导出及备份恢复。

详细的使用场景、目录说明与安全边界请从 [`README_FIRST.md`](README_FIRST.md) 开始。导航页源码构建与高级运维见 [`navigation/README.md`](navigation/README.md)，离线安装包的使用说明见 [`navigation/release/docs/DEPLOYMENT.md`](navigation/release/docs/DEPLOYMENT.md)。

## 隐私边界

公开源码不包含私人书签 HTML、数据库、备份、真实 `.env`、密码、Token、私钥或离线发布归档。需要用个人书签做本地回归时，通过 `NAV_PRIVATE_BOOKMARK_FIXTURE` 指向仓库外的 Netscape Bookmark HTML；该文件不会被复制进项目。

## 本地开发

Python `3.13.14` 由 `.python-version` 固定并使用 `uv`；Node.js `v24.18.0` 由 `.node-version` 固定并使用 `fnm`。

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --extra test
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv run --extra test python -W error -m pytest -q

cd ../frontend
fnm exec --using ../../.node-version npm ci
fnm exec --using ../../.node-version npm test -- --run
fnm exec --using ../../.node-version npm run typecheck
fnm exec --using ../../.node-version npm run build
```

## 安全与许可

发现安全问题时请遵循 [`SECURITY.md`](SECURITY.md)，不要在公开 Issue 中披露漏洞、凭据或私人书签数据。

本项目采用 [`AGPL-3.0-only`](LICENSE) 许可证。修改后的网络服务向用户提供时，需要遵守 GNU Affero General Public License 第 3 版的相应源代码提供义务。
