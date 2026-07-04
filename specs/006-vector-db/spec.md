# Feature Specification: 向量数据库 — HNSW 索引引擎

**Feature Branch**: `006-vector-db`

**Created**: 2026-07-14

**Status**: Draft

**Input**: 用户描述："设计并实现一个向量数据库，索引性能为先"

---

## 1. 核心概念

| 概念 | 定义 |
|------|------|
| **向量 (Vector)** | 固定维度的浮点数数组，表示一个数据点的 embedding |
| **索引 (Index)** | 基于 HNSW 算法构建的近似最近邻搜索结构，支持动态增删 |
| **集合 (Collection)** | 一个命名的向量集合，包含一个索引和关联的元数据存储 |
| **查询 (Query)** | 输入向量，返回索引中最近邻的 top-K 结果 |
| **距离度量 (Metric)** | 向量间相似度的计算方式，支持 cosine / dot_product |

---

## 2. [NEEDS CLARIFICATION] 假设说明

以下为合理假设，后续实现中如需调整可修改：

1. **索引算法**：采用 HNSW (Hierarchical Navigable Small World) 作为核心算法。HNSW 在 recall@10≥0.99 时仍能保持高 QPS，是当前 ANN 搜索的事实标准。
2. **默认向量维度**：以 768 维（OpenAI text-embedding-ada-002 的维度）作为基准设计，支持 128～4096 维。
3. **距离度量**：支持 cosine 和 dot_product 两种度量。cosine 通过 L2 归一化后使用内积等价实现。
4. **存储后端**：索引结构（图边、层级）存储在内存中，向量数据和元数据可选持久化到磁盘（JSON 或二进制格式）。

---

## 3. 功能需求

### FR-1: 创建集合 (Create Collection)

**描述**: 用户创建一个新的向量集合，指定维度、距离度量和 HNSW 参数。

**优先级**: P1

**输入**:
```
collection_name: str          # 集合名称，唯一标识
dimension: int                # 向量维度 (128 ≤ dimension ≤ 4096)
metric: Literal["cosine", "dot_product"]  # 距离度量
hnsw_params: {
  M: int = 16                # 每个节点的最大连接数 (4 ≤ M ≤ 128)
  ef_construction: int = 200 # 构建时的动态候选列表大小 (100 ≤ ef_construction ≤ 1000)
  random_seed: int = 42      # 随机种子，用于层级分配
}
```

**输出**: `Collection` 对象，包含唯一的集合 ID。

**边界条件**:
- 集合名称已存在 → 返回错误 `CollectionAlreadyExists`
- dimension 超出 [128, 4096] 范围 → 返回错误 `InvalidDimension`
- M 超出 [4, 128] 范围 → 返回错误 `InvalidHnswParam`
- ef_construction 超出 [100, 1000] 范围 → 返回错误 `InvalidHnswParam`

**验收标准**:
- 创建后集合存在且可查询（即使无数据，返回空结果）
- 创建耗时 < 10ms（纯内存操作）

---

### FR-2: 插入向量 (Insert Vectors)

**描述**: 向集合中批量插入向量及其可选的元数据。

**优先级**: P1

**输入**:
```
collection_name: str
vectors: List[{
  id: str                    # 向量唯一 ID
  vector: List[float]        # 浮点数数组，长度等于 dimension
  metadata: Optional[Dict]   # 可选的元数据键值对
}]
```

**输出**: 插入成功的向量数量 `int`

**边界条件**:
- 集合不存在 → 返回错误 `CollectionNotFound`
- 向量维度与集合 dimension 不匹配 → 返回错误 `DimensionMismatch`
- 向量列表为空 → 返回 0，不报错
- ID 重复 → 覆盖（upsert 语义），返回计数包含覆盖的条目
- 单次批量插入上限：10,000 条（超出时调用方应分批）

**验收标准**:
- 插入后搜索能召回新插入的向量
- 10 万条 768 维向量插入耗时 < 5s
- 内存增长与向量数量成线性关系

---

### FR-3: 搜索向量 (Search Vectors)

**描述**: 输入查询向量，返回集合中 top-K 个最近邻向量及其距离分数。

**优先级**: P1

**输入**:
```
collection_name: str
query_vector: List[float]    # 查询向量，长度等于 dimension
top_k: int                   # 返回结果数量 (1 ≤ top_k ≤ 1000)
ef_search: Optional[int]     # 搜索时的动态候选列表大小，默认 = ef_construction
```

**输出**:
```
List[{
  id: str                    # 向量 ID
  score: float               # 距离分数（cosine 范围 [-1,1]，越大越相似）
  metadata: Optional[Dict]   # 关联的元数据
}]
```

**边界条件**:
- 集合不存在 → 返回错误 `CollectionNotFound`
- 集合为空 → 返回空列表 `[]`
- query_vector 维度不匹配 → 返回错误 `DimensionMismatch`
- top_k > 集合大小 → 返回全部结果（不报错）
- ef_search 未指定 → 使用 ef_construction 作为默认值

**验收标准**:
- recall@10 ≥ 0.95（与暴力搜索对比）
- 10 万向量上 P99 延迟 < 5ms（top_k=10）
- 100 万向量上 P99 延迟 < 10ms（top_k=10）

---

### FR-4: 删除向量 (Delete Vectors)

**描述**: 从集合中删除指定 ID 的向量。

**优先级**: P2

**输入**:
```
collection_name: str
ids: List[str]               # 要删除的向量 ID 列表
```

**输出**: 实际删除的向量数量 `int`

**边界条件**:
- 集合不存在 → 返回错误 `CollectionNotFound`
- ID 列表为空 → 返回 0，不报错
- ID 不存在 → 跳过（不报错，不计入删除计数）
- 删除后索引结构需保持正确性（图边重新连接）

**验收标准**:
- 删除后搜索不再召回被删除的向量
- 删除 1 万条数据耗时 < 1s

---

### FR-5: 获取向量 (Get Vectors)

**描述**: 根据 ID 列表获取向量及其元数据。

**优先级**: P2

**输入**:
```
collection_name: str
ids: List[str]               # 要获取的向量 ID 列表
```

**输出**:
```
List[Optional[{
  id: str
  vector: List[float]
  metadata: Optional[Dict]
}]]
```
返回列表顺序与输入 ids 顺序一致，不存在的 ID 对应位置为 `None`。

**边界条件**:
- 集合不存在 → 返回错误 `CollectionNotFound`
- ID 列表为空 → 返回空列表 `[]`
- 部分 ID 不存在 → 对应位置返回 None

---

### FR-6: 持久化与加载 (Persist & Load)

**描述**: 将集合的索引结构和向量数据持久化到磁盘，并支持从磁盘加载恢复。

**优先级**: P2

**输入 (持久化)**:
```
collection_name: str
path: str                    # 磁盘路径
```

**输入 (加载)**:
```
path: str
```

**输出**: `Collection` 对象

**边界条件**:
- 路径不存在（加载时）→ 返回错误 `FileNotFound`
- 文件格式损坏 → 返回错误 `CorruptedData`
- 持久化时目标路径已存在 → 覆盖

**验收标准**:
- 持久化后加载的索引与原始索引搜索结果一致（相同查询返回相同 top-K）
- 100 万条 768 维数据的持久化耗时 < 30s
- 100 万条数据的加载耗时 < 30s

---

### FR-7: 集合信息 (Collection Stats)

**描述**: 查询集合的统计信息。

**优先级**: P3

**输入**:
```
collection_name: str
```

**输出**:
```
{
  name: str
  dimension: int
  metric: str
  total_vectors: int
  hnsw_params: { M, ef_construction }
  memory_usage_bytes: int    # 索引占用的内存估算
}
```

---

## 4. 架构设计

### 4.1 模块结构

```
vector_db/
├── __init__.py              # 公开 API
├── api.py                   # 统一入口，集合管理
├── collection.py            # Collection 数据类
├── index/
│   ├── hnsw.py              # HNSW 索引核心实现
│   ├── distance.py          # 距离度量函数
│   └── layer.py             # 层级分配 & 图结构
├── storage/
│   ├── memory_store.py      # 内存存储（向量 + 元数据）
│   └── disk_store.py        # 磁盘持久化
└── types.py                 # 类型定义 & 错误类型
```

### 4.2 HNSW 算法要点

| 参数 | 说明 |
|------|------|
| **M** | 每个节点每层的最大连接数。越大 recall 越高，但内存和构建时间增加 |
| **Mmax** | 每层最大连接数，通常 = M |
| **Mmax0** | 第 0 层最大连接数，通常 = 2×M |
| **ef_construction** | 构建时的动态候选集大小。越大构建越慢但索引质量越高 |
| **ef_search** | 搜索时的动态候选集大小。越大 recall 越高但查询越慢 |
| **mL** | 层级分配的归一化因子，通常 = 1/ln(M) |

层级分配公式: `l = floor(-ln(uniform(0,1)) * mL)`

### 4.3 距离度量实现

- **cosine**: 先对向量做 L2 归一化，然后使用内积计算。score = dot(normalize(a), normalize(b))，范围 [-1, 1]
- **dot_product**: 直接计算内积。score = dot(a, b)

搜索时按 score **降序**排列（越大越相似）。

---

## 5. 错误处理

| 错误类型 | 触发条件 | HTTP 类比 |
|----------|----------|-----------|
| `CollectionNotFound` | 集合名称不存在 | 404 |
| `CollectionAlreadyExists` | 创建时名称已存在 | 409 |
| `InvalidDimension` | 维度超出 [128, 4096] | 400 |
| `DimensionMismatch` | 向量维度与集合不匹配 | 400 |
| `InvalidHnswParam` | M/ef_construction 超出范围 | 400 |
| `FileNotFound` | 加载时路径不存在 | 404 |
| `CorruptedData` | 持久化文件损坏 | 500 |

所有错误类型继承自 `VectorDBError(Exception)`。

---

## 6. 接口定义 (API Surface)

### 6.1 Python API

```python
class VectorDB:
    def create_collection(
        name: str,
        dimension: int,
        metric: Literal["cosine", "dot_product"] = "cosine",
        M: int = 16,
        ef_construction: int = 200,
        random_seed: int = 42,
    ) -> Collection: ...

    def insert(
        name: str,
        vectors: list[dict],
    ) -> int: ...

    def search(
        name: str,
        query_vector: list[float],
        top_k: int = 10,
        ef_search: int | None = None,
    ) -> list[dict]: ...

    def delete(
        name: str,
        ids: list[str],
    ) -> int: ...

    def get(
        name: str,
        ids: list[str],
    ) -> list[dict | None]: ...

    def persist(
        name: str,
        path: str,
    ) -> None: ...

    @staticmethod
    def load(path: str) -> Collection: ...

    def stats(
        name: str,
    ) -> dict: ...
```

---

## 7. 性能指标

### 7.1 构建性能

| 数据规模 | 维度 | M | ef_construction | 目标耗时 |
|----------|------|---|-----------------|----------|
| 10 万 | 768 | 16 | 200 | < 5s |
| 100 万 | 768 | 16 | 200 | < 20s |

### 7.2 查询性能

| 数据规模 | top_k | ef_search | P99 延迟 | recall@10 |
|----------|-------|-----------|----------|-----------|
| 10 万 | 10 | 200 | < 5ms | ≥ 0.95 |
| 100 万 | 10 | 200 | < 10ms | ≥ 0.95 |
| 100 万 | 10 | 400 | < 20ms | ≥ 0.99 |

### 7.3 内存占用

| 数据规模 | 维度 | 估算内存 |
|----------|------|----------|
| 10 万 | 768 | ~120 MB |
| 100 万 | 768 | ~1.2 GB |

---

## 8. 验收标准

### 8.1 功能验收

1. **【P1】** 创建集合 → 插入 1,000 条 → 搜索 → 返回正确 top-K
2. **【P1】** 搜索结果的 recall@10 ≥ 0.95（与暴力搜索对比）
3. **【P2】** 插入后删除 → 搜索不再召回被删向量
4. **【P2】** 持久化 → 加载 → 搜索结果一致
5. **【P3】** 获取向量返回正确的向量和元数据

### 8.2 性能验收

1. **【P1】** 10 万向量构建耗时 < 5s
2. **【P1】** 在 10 万向量上搜索 top_k=10，P99 延迟 < 5ms
3. **【P1】** recall@10 ≥ 0.95（小规模验证）
4. **【P2】** 构建 100 万条 768 维向量耗时 < 20s
5. **【P2】** 在 100 万向量上搜索 top_k=10，P99 延迟 < 10ms

### 8.3 鲁棒性验收

1. 非法参数（维度超限、M 超限）返回明确的错误信息
2. 批量插入中部分 ID 重复时正常覆盖，不崩溃
3. 对空集合的搜索、删除操作正常返回
4. 持久化文件损坏时返回 `CorruptedData` 错误

---

## 9. 测试策略

### 9.1 单元测试

- `test_hnsw_build_search`: 构建索引并搜索，验证召回率
- `test_distance_cosine`: 验证 cosine 距离计算正确性
- `test_distance_dot`: 验证 dot_product 计算正确性
- `test_layer_assignment`: 验证层级分配的概率分布
- `test_collection_crud`: 创建/插入/删除/获取的 CRUD 操作

### 9.2 集成测试

- `test_full_pipeline`: 创建 → 插入 10,000 条 → 搜索 → 验证 top-K 正确
- `test_persist_load_roundtrip`: 持久化 → 加载 → 搜索一致性
- `test_upsert_behavior`: 重复 ID 插入后的覆盖行为

### 9.3 基准测试

- `bench_build`: 不同数据规模下的构建速度
- `bench_search`: 不同 ef_search 和 top_k 下的查询延迟
- `bench_recall`: 不同参数组合下的 recall@K

---

## 10. 非功能性需求

- **线程安全**: 索引操作（插入/搜索/删除）应支持多线程并发读，写入需加锁
- **内存效率**: 向量数据以 `numpy.ndarray` 或 `array('f')` 存储，避免 Python float 对象开销
- **可扩展性**: 索引算法实现应允许未来替换为其他 ANN 算法（如 IVF-PQ、NSG）
- **日志**: 关键操作（创建集合、插入批量、持久化）记录 INFO 级别日志
