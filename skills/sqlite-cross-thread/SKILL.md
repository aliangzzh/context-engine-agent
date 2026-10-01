---
name: sqlite-cross-thread
description: 在多线程服务里用 SQLite（或任何有线程亲和性的资源）必须显式关掉线程检查并用锁串行化写入，否则并发请求会随机报 ProgrammingError，而且在单线程测试里永远复现不出来。
tags: [sqlite, concurrency, storage, threading]
trigger: [sqlite, 多线程, 跨线程, 线程, 数据库, 并发, 锁, check_same_thread, 连接]
stack: [python]
status: active
version: 1
updated: 2026-09-30
---

# 多线程服务里的 SQLite 连接

## 规则（检查清单）

1. 先问：**这个资源的线程亲和性是什么？** 进程级单例（数据库连接、文件句柄、缓存）
   在多线程服务里都要单独确认一遍。
2. SQLite 连接默认**只能由创建它的线程使用** → `check_same_thread=False`，
   但**必须自己加锁**串行化写入（关掉检查不等于变线程安全）。
3. 开 `PRAGMA journal_mode=WAL`：单进程读写并发下更稳。
4. 一组写操作要**整体提交或整体回滚**（本项目 `save()` 是"先删后写"，中途失败必须回滚，
   否则历史被删一半）。
5. **必须补并发 / 回滚的回归测试**——这类问题在单线程路径上永远测不出来。

## 反例（本仓库真实发生过）

**SQLite 对象跨线程使用**

- 现象：并发请求时随机抛 `sqlite3.ProgrammingError: SQLite objects created in a thread can
  only be used in that same thread`
- 根因：存储层把"一个进程一个连接"当成了默认安全；但 HTTP 服务器是**多线程**的
  （stdlib `ThreadingHTTPServer` / FastAPI 的线程池），连接会活过创建它的线程
- 修复：`app/storage/db.py` 用 `check_same_thread=False` + `timeout`，并把并发访问
  收进 `SQLChatStore._lock` 串行化
- 验证：`backend/tests/test_storage.py`（事务回滚 + 跨线程/并发用例）

## 怎么自查你正在犯这个错

- 有没有"进程级单例资源"没被问过线程亲和性？（连接 / 句柄 / 缓存 / 索引对象）
- 关掉 `check_same_thread` 之后，**写入有没有锁**？（只关检查 = 把报错变成更难查的数据竞争）
- 你的测试是不是全在单线程里跑？（那就等于没测并发）
