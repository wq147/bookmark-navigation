# SQLite 连接生命周期修复设计

## 问题

Python 3.13.14 会在未显式关闭的 `sqlite3.Connection` 被回收时发出 `ResourceWarning`。当前后端把 `with sqlite3.connect(...)` 当作关闭连接的上下文管理器，但该上下文只提交或回滚事务，不调用 `close()`。部分测试还创建了未在异常路径中 `dispose()` 的 SQLAlchemy engine。

普通测试的业务断言通过，但全局 `-W error` 会把这些资源警告提升为失败，掩盖真正的测试结果，也表明连接生命周期不完整。

## 方案

生产代码统一通过一个内部 `_connect_sqlite()` 助手返回 `contextlib.closing(sqlite3.connect(path))`。所有原生 SQLite 读取、快照和恢复路径都使用该助手，因此正常路径和异常路径都会显式关闭连接，同时保留现有的显式 `commit()` 和原子发布流程。

测试中直接打开 SQLite 的位置也使用 `closing()`。自行创建 SQLAlchemy engine 的夹具和测试使用 `try/finally` 调用 `engine.dispose()`，不依赖垃圾回收。

## 回归测试

新增一个跟踪 `sqlite3.Connection.close()` 的测试：调用真实 `create_backup()` 后，断言源连接和目标连接全部关闭。该测试在旧实现上失败，在使用 `closing()` 后通过。

随后运行受影响的备份、恢复和模型测试，最终必须在 Python 3.13.14 下通过：

```bash
UV_CACHE_DIR=/tmp/bookmark-navigation-uv-cache \
  uv run --extra test python -W error -m pytest -q
```

完成标准是 `152 passed, 2 skipped`，不添加警告过滤器，不修改 Alembic 历史迁移，不升级依赖。

## 边界

- 不改变备份文件格式、恢复顺序、事务语义或 API。
- 不修改数据库迁移历史。
- 不通过 pytest 配置或命令行忽略 `ResourceWarning`。
- 不初始化 Git、发布或部署。
