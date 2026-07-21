# GitHub 仓库加固设计

## 目标

为公开的单人维护仓库建立可执行的 Pull Request 门禁、核心持续集成和 GitHub 安全设置。所有日常改动通过功能分支和 Pull Request 进入 `main`，合并前必须由自动检查证明后端与前端仍可测试和构建。

## 当前约束

- 仓库由一人维护，没有可承担强制审批的协作者。
- Pull Request 必须作为进入 `main` 的唯一日常路径，但所需批准数为 `0`，避免维护者无法合并自己的改动。
- Python 固定为 `3.13.14`，使用 uv 和 `navigation/backend/uv.lock`。
- Node.js 固定为 `v24.18.0`，使用 npm 和 `navigation/frontend/package-lock.json`。
- 首期 CI 不运行 Docker、Playwright E2E、部署、离线包构建或发布。
- CI 和 Ruleset 分阶段启用：先让状态检查在 GitHub 上成功出现，再把它们设为 `main` 的强制门禁。

## CI 架构

新增一个 `.github/workflows/ci.yml`，在以下事件运行：

- 目标分支为 `main` 的 Pull Request；
- 合并或直接写入 `main` 后的 push，用作合并结果复验。

工作流仅授予 `contents: read` 权限。同一 Pull Request 或同一分支的新运行会取消旧运行，避免重复占用执行资源。

工作流包含两个并行且名称稳定的 Job：

### Backend

- 检出源码并安装项目固定的 Python 与 uv；
- 以锁文件为准安装测试依赖；
- 运行 `python -W error -m pytest -q`；
- 使用 `bash -n` 验证三份部署/发布脚本；
- 复用后端文档回归测试验证公开元数据和脱敏边界；
- 新增仓库级 Markdown 链接回归测试，扫描源码仓库中的 Markdown，忽略外部 URL、页内锚点和生成目录，并要求所有本地相对目标存在。

Job 名固定为 `Backend`，供 Ruleset 作为必需状态检查引用。私人书签 fixture 不进入 CI，相关测试继续按设计跳过。

### Frontend

- 检出源码并安装 `.node-version` 指定的 Node.js；
- 使用 `npm ci` 严格按锁文件安装依赖；
- 依次运行 `npm test -- --run`、`npm run typecheck` 和 `npm run build`。

Job 名固定为 `Frontend`，供 Ruleset 作为必需状态检查引用。Playwright E2E 留待具备测试服务、浏览器、初始化账号和脱敏 fixture 的后续阶段。

## `main` Ruleset

CI 首次成功并在 GitHub 中产生 `Backend`、`Frontend` 状态后，创建一个 Active Ruleset，目标为默认分支 `main`：

- 必须通过 Pull Request 合并；
- 所需批准数为 `0`；
- 合并前必须通过 `Backend` 与 `Frontend`；
- 合并前分支必须更新到最新 `main`；
- 要求线性提交历史；
- 禁止强制推送；
- 禁止删除 `main`；
- 首期不要求签名提交；
- 不设置日常绕过权限。

如果 CI 配置损坏到任何修复 PR 都无法满足门禁，仓库管理员可在 GitHub Settings 中临时停用 Ruleset，合并修复后立即重新启用。该恢复流程仅用于门禁自身故障，不作为绕过正常 CI 的开发方式。

## GitHub 安全设置

在仓库 Settings 的安全配置中启用：

- Dependency Graph；
- Dependabot Alerts；
- Dependabot Security Updates；
- Private Vulnerability Reporting；
- GitHub 当前为该公开仓库提供的 Secret Scanning 与 Push Protection。

首期不创建 Dependabot 定期 Version Updates 配置，避免单人仓库产生大量非安全升级 PR；不启用 CodeQL、Docker 镜像扫描或第三方安全 Action。安全告警只提示或创建安全修复 PR，不自动绕过 CI 和 Ruleset。

## 实施顺序

1. 在 `chore/github-repository-hardening` 分支提交本设计和实施计划。
2. 在该分支新增 CI 工作流并完成本地等价验证。
3. 推送分支，创建首个 Pull Request。
4. 确认 GitHub 上 `Backend`、`Frontend` 均通过后合并。
5. 在 GitHub Settings 中启用 Ruleset 和安全设置。
6. 创建一个不改变运行行为的小型测试 Pull Request，确认直接推送受阻、CI 门禁生效且单人可在零审批条件下合并。

## 完成标准

- Pull Request 页面稳定显示 `Backend` 与 `Frontend` 两个检查；
- 任一检查失败时无法合并到 `main`；
- 未通过 Pull Request 的普通直接推送和强制推送被拒绝；
- 维护者可以在两个检查通过且分支最新时合并自己的 Pull Request；
- Dependency Graph、Dependabot Alerts、Security Updates 和 Private Vulnerability Reporting 已启用；
- 仓库中没有新增密码、Token、私人书签、数据库、备份、真实 `.env` 或发布归档；
- Docker、E2E、部署和 GitHub Release 仍明确留在后续独立阶段。
