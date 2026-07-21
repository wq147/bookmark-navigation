# 实施步骤与验收任务分解的开发历史

本文是 Bookmark Navigation 实施计划的索引。这些文档保留任务拆分、测试顺序、服务器验收和发布检查点；它们是开发过程证据，不是当前部署命令的唯一事实来源。

| 实施计划 | 任务范围 |
| --- | --- |
| [私人书签导航实施计划](2026-07-13-private-bookmark-navigation.md) | FastAPI/Vue 应用、三栏工作台、认证、导入导出、备份恢复和真实 V5 验收 |
| [Linux amd64 离线安装器实施计划](../../offline-amd64-installer-implementation-plan-2026-07-14.md) | 发布契约、首次安装、保留数据升级、改端口和 Linux amd64 服务器验收 |
| [书签项目文档整理实施计划](2026-07-14-bookmark-documentation-consolidation.md) | 文档合同测试、主入口整理、文件职责说明和本地交付物清理 |
| [本地开发环境实施计划](2026-07-21-local-development-environment.md) | 使用 uv 与 fnm 重建、锁定并验证独立开发环境 |
| [SQLite 连接生命周期实施计划](2026-07-21-sqlite-connection-lifecycle.md) | 通过 TDD 修复原生 SQLite 与测试 engine 的资源释放 |
| [GitHub 仓库加固实施计划](2026-07-21-github-repository-hardening.md) | Markdown 链接测试、核心 CI、首个 PR、main Ruleset、安全设置和门禁验收 |

## 阅读方式

- 需要回看当时如何分解开发与验收任务时，阅读对应计划。
- 需要部署当前版本时，使用 [`README_FIRST.md`](../../../../README_FIRST.md) 导航到当前权威手册。
- 历史计划中的版本、端口或命令可能已被后续实现更新，不应直接代替当前运维文档。
