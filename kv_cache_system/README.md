# KV Cache 缓存系统

高性能 KV Cache 缓存系统，专为 LLM 推理场景设计，支持极致性能的缓存存取。

## 项目结构

```
kv_cache_system/
├── spec.md              # 规格文档（本文）
├── src/
│   ├── __init__.py
│   ├── cache.py         # 缓存核心
│   ├── eviction.py      # 淘汰策略
│   ├── storage.py       # 存储后端
│   └── config.py        # 配置
├── tests/
│   ├── __init__.py
│   ├── test_cache.py
│   ├── test_eviction.py
│   └── test_storage.py
└── benchmarks/
    └── bench_cache.py
```
