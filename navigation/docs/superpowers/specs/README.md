# 产品、安全和发布设计决策的开发历史

本文是 Bookmark Navigation 设计文档的索引。这些文档记录开发当时的产品范围、安全边界、发布方式和文档结构决策；当前运行和部署仍以 `README_FIRST.md`、`navigation/README.md`、`.env.example` 和 `release/docs/DEPLOYMENT.md` 为准。

| 设计文档 | 记录内容 |
| --- | --- |
| [私人书签导航产品与安全设计](2026-07-13-private-bookmark-navigation-design.md) | 三栏工作台、认证、数据安全、导入导出和自建方案的初始产品决策 |
| [Linux amd64 离线安装包设计](../../offline-amd64-installer-design-2026-07-14.md) | 离线交付物、首装与升级接口、持久化、Docker 网络和安全边界 |
| [书签项目文档整理设计](2026-07-14-bookmark-documentation-consolidation-design.md) | 唯一主入口、权威文档分工、历史记录保留和本地交付物边界 |
| [本地开发环境设计](2026-07-21-local-development-environment-design.md) | uv、fnm、Python 与 Node.js 版本锁定及独立环境边界 |
| [SQLite 连接生命周期修复设计](2026-07-21-sqlite-connection-lifecycle-design.md) | Python 3.13 资源警告、原生连接关闭和测试 engine 销毁策略 |
| [GitHub 仓库加固设计](2026-07-21-github-repository-hardening-design.md) | 单人 PR 流程、核心 CI、main Ruleset、Dependabot 与私密漏洞报告策略 |

## 阅读方式

- 需要理解“为什么这样设计”时，阅读本索引中的历史设计。
- 需要执行当前部署或升级时，返回 [`README_FIRST.md`](../../../../README_FIRST.md) 选择当前手册。
- 历史设计不会随后续实现反复改写，因此与当前代码冲突时以当前源码、配置和权威 README 为准。
