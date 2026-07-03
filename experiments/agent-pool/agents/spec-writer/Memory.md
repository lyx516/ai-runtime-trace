# Memory: spec-writer
> Max length: 3000 chars. Write runtime experience here.



-----
## 嵌入式KV存储引擎规格文档

### 功能需求
1. **TTL过期**: 支持为每个key设置过期时间（秒级精度），过期后自动删除。
2. **WAL预写日志**: 所有写操作先写入WAL文件再更新内存，重启时从WAL恢复。
3. **LRU缓存**: 内存中维护LRU缓存，淘汰最久未访问的key。
4. **读写锁并发控制**: 支持多读单写，读操作不阻塞读，写操作互斥。
5. **Python绑定**: 纯Python实现，对外暴露简单API。

### 输入输出定义
- `put(key: str, value: bytes, ttl: Optional[int] = None)` -> `None`
- `get(key: str)` -> `Optional[bytes]`（过期返回None）
- `delete(key: str)` -> `bool`
- `flush()` -> `None`（强制写入WAL并刷盘）

### 边界条件
- key为空字符串、None、超长（>1024字符）
- value为空或None
- ttl为0或负数视为立即过期
- 并发读写同一key
- WAL文件损坏或不存在
- 内存缓存满时LRU淘汰

### 错误处理
- 无效key类型：抛出TypeError
- WAL写入失败：抛出IOError并回滚内存状态
- 恢复时WAL校验失败：抛出CorruptedWALError

### 验收标准
1. 单元测试覆盖所有API（put/get/delete/flush）
2. TTL过期测试：设置ttl=1，sleep(1.5)后get返回None
3. WAL持久化测试：写入数据，重启引擎，get返回相同数据
4. LRU淘汰测试：缓存容量2，写入3个key，最早写入的被淘汰
5. 并发测试：多线程读写，无数据竞争