# Acceptance Method — 2026-07-13

## 公开说明

本文由一次真实私人书签数据验收记录脱敏而来。原始 Netscape Bookmark HTML、个人目录名称、精确书签/目录数量、数据库、备份、密码和主机信息不属于公开源码，也不能从原知识库复制进本项目。

公开版本保留验收方法、通过条件和已修复的回归点。需要复验个人数据时，在本地设置 `NAV_PRIVATE_BOOKMARK_FIXTURE` 指向仓库外的 HTML 文件；自动化测试会从该文件动态计算期望书签状态，不依赖公开文档中的固定数量。

## 验收范围

- 未登录的书签 API 与导出 API 返回 401。
- 导入先执行预览，再由已认证且携带 CSRF 的请求应用。
- 对规范化 URL 去重后，导入结果与源文件的书签集合一致。
- 导出 HTML 与源文件逐 URL 比较路径和 Netscape 属性，而不是分别比较两个无关集合。
- 根目录属性、所有目录路径及目录属性能够往返保留。
- 导出结果不存在重复的规范化 URL。
- 备份恢复前自动创建保护快照，恢复后撤销现有登录会话。
- Alembic 迁移从空数据库升级到当前 head。

## 隔离与隐私

验收数据库、备份目录、导出 HTML 和一次性密码文件必须放在临时目录，不写入仓库。测试完成后删除临时数据；任何失败日志或截图在共享前都要移除 URL、标题、目录名、账号和主机信息。

可选私人样本测试未配置时应显示为跳过，而不是失败：

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test python -m pytest \
  tests/test_real_v5_import.py tests/test_export_backup.py -q
```

如需在受控本地环境运行：

```bash
export NAV_PRIVATE_BOOKMARK_FIXTURE=/absolute/path/outside/repository/bookmarks.html
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test python -m pytest \
  tests/test_real_v5_import.py tests/test_export_backup.py -q
unset NAV_PRIVATE_BOOKMARK_FIXTURE
```

## 已修复的回归点

原验收发现空目录未进入导入批次。迁移 `0006_import_empty_folders` 增加目录清单后，导入可以保留空目录、目录属性与工具栏根属性。升级会把无法重建目录清单的旧 `previewed` 批次标记为 `expired`，要求重新上传并预览；降级删除清单列，但不会重新激活这些批次。

另有回归测试证明书签状态比较会发现两个 URL 的路径被交换，避免“路径集合与属性集合分别相等”造成的假阳性。

## 当前验证命令

后端使用项目固定的 Python 与 uv：

```bash
cd navigation/backend
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache uv sync --extra test
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test python -W error -m pytest -q
```

前端使用项目固定的 Node.js 与 fnm：

```bash
cd navigation/frontend
fnm exec --using ../../.node-version npm ci
fnm exec --using ../../.node-version npm test -- --run
fnm exec --using ../../.node-version npm run typecheck
fnm exec --using ../../.node-version npm run build
```

## 环境相关验证

Playwright E2E 需要已安装的浏览器和可用测试服务。Compose/镜像/健康检查需要 Docker 环境。缺少这些条件时必须记录“未执行”和原因，不能用历史结果代替当前验证。

Docker 可用时至少执行：

```bash
cd navigation
docker compose config
```

本地公开整理阶段不得启动或修改生产服务与数据，也不得执行 `docker compose down --volumes`。
