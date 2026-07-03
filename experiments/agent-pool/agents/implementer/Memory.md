# Memory: 代码实现者
> Max length: 3000 chars. Write runtime experience here.




-----
## KV存储引擎架构

### 核心组件
1. **内存存储**：`dict` + `OrderedDict`(LRU)
2. **WAL**：追加写二进制文件，格式 [key_len:4B][key][value_len:8B][value][ttl:8B]，删除记录用 key_len=-1
3. **TTL**：时间戳比较，后台惰性删除 + 每次get检查
4. **LRU**：容量限制，淘汰最久未访问
5. **读写锁**：自定义 `ReadWriteLock` 类，允许多读单写

### 并发模型
- 写操作：获取写锁 → 写WAL → 更新内存 → 释放写锁
- 读操作：获取读锁 → 读取内存 → 释放读锁
- 后台线程：定期清理过期key

### 边界情况
- WAL文件损坏：忽略无效记录
- 空key/超大key：合理限制
- 并发关闭：关闭后拒绝操作
- TTL=0：永不过期