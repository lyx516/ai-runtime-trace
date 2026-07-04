# 代码审查报告 — 向量数据库 (vector_db)

**审查日期**: 2026-07-14  
**审查者**: 代码审查专家  
**审查范围**: `vector_db/` 目录 vs `vector_db/spec.md`（版本 1.0）

---

## 摘要

代码实现了 HNSW 索引的核心算法（层级分配、图构建、搜索、删除），但在**模块完整性**、**API 层**、**集合管理**、**参数校验**和**持久化**方面与 spec 存在显著差距。以下逐条列出问题。

---

## 严重问题

### S1. [CRITICAL] 缺少多个必需模块 — 违反 spec §4.1

**Spec 要求**: 架构设计 §4.1 定义了模块结构：
```
vector_db/
├── __init__.py          # 公开 API：VectorDB 类
├── types.py             # 类型定义 & 错误类型
├── index/
│   ├── __init__.py
│   ├── hnsw.py          # HNSW 索引核心
│   ├── layer.py         # 层级分配逻辑
│   └── distance.py      # 距离度量函数
├── collection.py        # 集合管理：Collection 类
├── serialization.py     # 索引序列化/反序列化
└── spec.md
```

**实际情况**: 仅有以下文件存在：
- `vector_db/types.py` ✅
- `vector_db/index/distance.py` ✅
- `vector_db/index/hnsw.py` ✅
- `vector_db/index/layer.py` ✅
- `vector_db/spec.md` ✅

**缺失文件**:
- `vector_db/__init__.py` — 无公开 API 入口（spec §5.1 定义的 `VectorDB` 类）
- `vector_db/index/__init__.py` — 缺少包初始化文件
- `vector_db/collection.py` — 无 `Collection` 类（spec §5.2）
- `vector_db/serialization.py` — 无序列化/反序列化（spec FR-05）

**影响**: 
- 用户无法通过 `from vector_db import VectorDB` 使用数据库
- 没有集合管理逻辑（创建、获取、列出、删除集合）— FR-01 完全未实现
- 没有持久化功能 — FR-05 完全未实现
- 没有 `Collection` 对象返回给用户

---

### S2. [CRITICAL] 缺少 FR-01 集合管理 — 违反 spec FR-01

**Spec 要求** (FR-01):
- FR-01-01: 支持创建集合，指定向量维度和距离度量类型（P0）
- FR-01-02: 支持删除集合（P0）
- FR-01-03: 支持列出所有集合（P1）
- FR-01-04: 支持获取集合统计信息（向量总数、维度、索引状态）（P1）

**实际情况**: 
- `vector_db/__init__.py` 不存在，没有 `VectorDB` 入口类
- `vector_db/collection.py` 不存在，没有 `Collection` 类
- 没有任何集合管理逻辑

**代码位置**: 整个 `vector_db/` 目录下无集合管理相关代码。

**影响**: FR-01 的四个子需求（包括两个 P0 优先级）全部未实现。

---

### S3. [CRITICAL] 缺少 FR-05 索引持久化 — 违反 spec FR-05

**Spec 要求** (FR-05):
- FR-05-01: 支持将索引序列化保存到磁盘（P2）
- FR-05-02: 支持从磁盘加载已保存的索引（P2）

**实际情况**: 
- `vector_db/serialization.py` 不存在
- `HNSWIndex` 类中没有 `save`/`load` 方法

**影响**: 整个 FR-05（P2 优先级）完全缺失。

---

## 参数校验问题

### P1. [HIGH] `HNSWIndex.__init__` 缺少参数边界校验 — 违反 spec §6.1

**Spec 要求** (§6.1 输入边界):

| 参数 | 最小值 | 最大值 | 超出处理 |
|------|--------|--------|----------|
| dimension | 128 | 4096 | 抛出 InvalidDimension |
| M | 4 | 128 | 截断到边界值 |
| ef_construction | 100 | 1000 | 截断到边界值 |

**代码位置**: `vector_db/index/hnsw.py` 第 52-68 行 (`__init__`)

**实际情况**: `HNSWIndex.__init__` 直接接受参数，没有任何校验：
```python
def __init__(
    self,
    dimension: int,
    metric: MetricType,
    M: int = 16,
    ef_construction: int = 200,
    random_seed: int = 42,
) -> None:
```
没有检查 `dimension` 范围，没有检查 `M` 范围，没有检查 `ef_construction` 范围。

**影响**: 用户可以创建 dimension=1 或 M=200 的索引，导致后续操作异常或内存溢出。

---

### P2. [HIGH] `insert` 方法缺少向量维度校验 — 违反 spec FR-02-01 & §7.1

**Spec 要求** (FR-02-01 & §7.1): 插入时如果向量维度与集合维度不匹配，抛出 `DimensionMismatch`。

**代码位置**: `vector_db/index/hnsw.py` 第 121-151 行

**实际情况**: `insert` 方法没有检查 `entry.vector` 的长度是否等于 `self.dimension`。如果传入维度不匹配的向量，后续的距离计算会引发 NumPy 内部错误（如广播异常），而非友好的 `DimensionMismatch` 错误。

---

### P3. [MEDIUM] `search` 方法缺少查询向量维度校验 — 违反 spec §5.2 & §7.1

**Spec 要求** (§5.2 `Collection.search`): 查询时如果向量维度不匹配，返回错误 `DimensionMismatch`。

**代码位置**: `vector_db/index/hnsw.py` 第 255-303 行

**实际情况**: `search` 方法没有检查 `query` 向量的维度是否等于 `self.dimension`。

---

### P4. [MEDIUM] 缺少集合名称校验 — 违反 spec §5.1 & §6.1

**Spec 要求** (§5.1): 集合名称长度 1~128 字符，只含 `[a-zA-Z0-9_-]`，超出抛出 `ValueError`。

**实际情况**: 由于 `collection.py` 和 `__init__.py` 不存在，集合名称校验逻辑完全缺失。

---

### P5. [MEDIUM] `top_k` 和 `ef_search` 缺少边界截断 — 违反 spec §6.1

**Spec 要求** (§6.1):
- `top_k`: 范围 [1, 1000]，超出截断到边界值
- `ef_search`: 范围 [1, 1000]，超出截断到边界值；且 `ef_search ≥ top_k`

**代码位置**: `vector_db/index/hnsw.py` 第 255-260 行

**实际情况**: `search` 方法没有对 `top_k` 和 `ef_search` 做任何边界检查或截断。

---

## 功能实现问题

### F1. [HIGH] `_select_neighbors` 实现过于简单 — 违反 HNSW 算法规范

**Spec 要求**: spec 未明确要求实现启发式选择，但基于 HNSW 论文标准实现，`_select_neighbors` 应使用启发式选择算法（Heuristic Selection）来提升图质量。

**代码位置**: `vector_db/index/hnsw.py` 第 305-327 行

**实际情况**: `_select_neighbors` 简单地取前 `max_connections` 个最近邻：
```python
selected = [node_id for node_id, _ in candidates[:max_connections]]
```
没有实现论文中的启发式选择（添加最远邻居时检查是否有更优替代）。这会导致索引质量下降，recall 可能不达标（spec §8.3 要求召回率 ≥ 95%）。

---

### F2. [MEDIUM] `_remove_node` 删除后未清理空层 — 违反 spec §4.2

**代码位置**: `vector_db/index/hnsw.py` 第 359-399 行

**实际情况**: 删除节点后，如果某层变为空，`self.graph` 中仍保留该层的空字典。这不会导致功能错误，但会浪费内存并可能导致搜索时遍历空层。

---

### F3. [MEDIUM] `assign_level` 使用 `self.max_level` 作为上限 — 违反 HNSW 论文标准

**Spec 要求**: spec 未明确指定，但 HNSW 论文中层级分配应使用全局最大层级上限，而非当前 max_level。

**代码位置**: `vector_db/index/hnsw.py` 第 137 行

**实际情况**: `assign_level` 的 `max_level` 参数来自 `self.max_level`（当前最大层级）。当索引为空时 `max_level=0`，第一个插入的节点只能分配到 level 0。虽然这不会导致功能错误，但会影响索引的层次结构质量。

---

### F4. [LOW] `compute_max_level` 函数未被使用 — 违反 spec §4.2

**代码位置**: `vector_db/index/layer.py` 第 42-63 行

**实际情况**: `compute_max_level` 函数已实现，但在 `HNSWIndex` 中从未被调用。`HNSWIndex` 使用 `self.max_level` 动态维护最大层级，而不是用此函数估算。

---

## 代码质量问题

### Q1. [MEDIUM] 缺少 `__init__.py` 文件导致包无法导入 — 违反 spec §4.1

**代码位置**: `vector_db/` 和 `vector_db/index/`

**实际情况**: 两个目录都缺少 `__init__.py` 文件，导致 `vector_db` 无法作为 Python 包被导入。

---

### Q2. [MEDIUM] `NDArrayF32` 类型标注不正确 — 违反 spec §4.1 类型定义

**代码位置**: `vector_db/types.py` 第 32-33 行

**实际情况**: `NDArrayF32 = "np.ndarray[np.float32]"` 是一个字符串标注，无法被类型检查器正确识别。应使用 `numpy.typing.NDArray[np.float32]`。

---

### Q3. [LOW] 定义了 logger 但从未使用

**代码位置**: `vector_db/index/hnsw.py` 第 36 行

**实际情况**: `hnsw.py` 中定义了 `logger = logging.getLogger(__name__)`，但没有任何地方使用 `logger.info()` 或 `logger.debug()` 记录操作日志。

---

### Q4. [LOW] `_search_layer` 中 `ef` 参数可能小于 1 — 违反 spec §6.1

**代码位置**: `vector_db/index/hnsw.py` 第 191-253 行

**实际情况**: `_search_layer` 接受 `ef` 参数，但在顶层搜索时传入 `ef=1`。当 `ef=1` 时，`results` 堆中只有一个元素，`results[0][0]` 访问是安全的。但如果未来传入 `ef=0`，会导致 `results[0]` 索引错误。建议增加 `ef >= 1` 的断言。

---

### Q5. [LOW] `_shrink_connections` 时间复杂度较高

**代码位置**: `vector_db/index/hnsw.py` 第 329-357 行

**实际情况**: `_shrink_connections` 对每个邻居单独调用 `compute_similarity`，可以改为批量计算以利用 NumPy 的向量化能力。

---

## Spec 与代码不一致

### I1. [MEDIUM] `InvalidHnswParam` 错误类已定义但未使用 — 违反 spec §7.1

**Spec 要求** (§7.1): `InvalidHnswParam` 应在 M/ef_construction 超出范围时抛出。

**代码位置**: `vector_db/types.py` 第 78-85 行

**实际情况**: `InvalidHnswParam` 类已定义，但没有任何代码使用它（因为 `HNSWIndex.__init__` 未做校验）。

---

### I2. [MEDIUM] `CorruptedData` 错误类已定义但未使用 — 违反 spec §7.1

**Spec 要求** (§7.1): 文件格式损坏时返回 `CorruptedData` 错误。

**代码位置**: `vector_db/types.py` 第 88-95 行

**实际情况**: `CorruptedData` 类已定义，但由于 `serialization.py` 不存在，该错误类从未被使用。

---

### I3. [MEDIUM] `FileNotFound` 错误类已定义但未使用 — 违反 spec §7.1

**Spec 要求** (§7.1): 加载时路径不存在时抛出 `FileNotFound`。

**代码位置**: `vector_db/types.py` 第 98-102 行

**实际情况**: `FileNotFound` 类已定义，但由于 `serialization.py` 不存在，该错误类从未被使用。

---

### I4. [LOW] `CollectionStats` 类已定义但未使用 — 违反 spec FR-01-04

**Spec 要求** (FR-01-04): 支持获取集合统计信息。

**代码位置**: `vector_db/types.py` 第 145-178 行

**实际情况**: `CollectionStats` 类已定义（包含 `to_dict()` 方法），但由于 `collection.py` 不存在，从未被实例化或使用。

---

### I5. [LOW] `InvalidID` 错误类在 spec §7.1 中列出但 `types.py` 中未定义

**Spec 要求** (§7.1): `InvalidID` — ID 为空字符串或含非法字符时抛出。

**代码位置**: `vector_db/types.py`

**实际情况**: 在 `types.py` 中搜索不到 `InvalidID` 类的定义。spec 中明确列出了此错误类，但代码未实现。

---

## 总结

| 类别 | 数量 | 严重程度 |
|------|------|----------|
| 严重问题 (S) | 3 | 缺少模块、缺少集合管理、缺少持久化 |
| 参数校验 (P) | 5 | 缺少维度/M/ef_construction/top_k/ef_search/名称校验 |
| 功能问题 (F) | 4 | select_neighbors 简化、空层清理、层级分配、未使用函数 |
| 代码质量 (Q) | 5 | 缺少 __init__.py、类型标注、日志、断言、性能 |
| 不一致 (I) | 5 | 错误类未使用、CollectionStats 未使用、InvalidID 缺失 |

**总体评价**: 核心 HNSW 算法实现基本正确（插入、搜索、删除流程完整），但存在以下关键缺失：
1. **模块完整性** — 缺少 `__init__.py`、`collection.py`、`serialization.py`，导致无法作为包使用
2. **API 层** — 没有 `VectorDB` 入口类和 `Collection` 集合管理类（两个 P0 需求）
3. **持久化** — 整个 FR-05 未实现
4. **参数校验** — 所有边界条件均未检查，违反 spec §6.1
5. **错误类未使用** — 定义了 4 个错误类但未使用，1 个错误类未定义

建议优先补齐缺失模块（`__init__.py`、`collection.py`、`serialization.py`），然后补充参数校验和边界检查。
