# VectorDB — System Architecture Design (Revised)

## 1. Overview

A lightweight, embedded vector database implemented in **pure Python with numpy acceleration**.
Supports cosine similarity and Euclidean distance search with metadata-based (tags) filtering.
Designed for simplicity, correctness, and reasonable performance on datasets up to ~100K vectors.

**Revision history**: v2 — addresses critic feedback on data safety, slot allocation performance,
filter optimization, NaN/inf handling, and exception safety.

## 2. Architecture

```
┌─────────────────────────────────────────────┐
│              VectorDB API                    │
│  insert(id, vector, tags)                   │
│  upsert(id, vector, tags)                   │
│  search(query, k, metric, filter)           │
│  delete(id)                                 │
│  get(id)                                    │
│  clear()                                    │
│  list_ids()                                 │
└──────────┬──────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────┐
│              Query Engine                    │
│  ┌────────────────┐  ┌──────────────────┐   │
│  │  Pre-filter    │  │  Similarity      │   │
│  │  (tags: dict   │──│  Computation     │   │
│  │   or callable) │  │  (numpy batch)   │   │
│  └────────────────┘  └────────┬─────────┘   │
└───────────────────────────────┼─────────────┘
                                │
┌───────────────────────────────▼─────────────┐
│              Storage Layer                   │
│  ┌──────────────┐  ┌──────────┐  ┌───────┐  │
│  │  vectors     │  │  ids     │  │ tags  │  │
│  │  normalized  │  │  (dict)  │  │(dict) │  │
│  │  (np.ndarray)│  └──────────┘  └───────┘  │
│  └──────────────┘                            │
│  ┌──────────────┐  ┌──────────────┐          │
│  │  active mask │  │  free_list   │          │
│  │  (np.ndarray)│  │  (List[int]) │          │
│  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐                            │
│  │ threading.Lock│                           │
│  └──────────────┘                            │
└──────────────────────────────────────────────┘
```

## 3. Data Structures

### 3.1 Vector Storage

| Component | Type | Shape | Purpose |
|-----------|------|-------|---------|
| `_vectors` | `np.ndarray(float32)` | `(capacity, dim)` | Raw vector data |
| `_normalized` | `np.ndarray(float32)` | `(capacity, dim)` | L2-normalized vectors (for cosine) |
| `_active` | `np.ndarray(bool)` | `(capacity,)` | Active/deleted tracking |
| `_capacity` | `int` | — | Current allocated rows |

### 3.2 ID Management

| Component | Type | Purpose |
|-----------|------|---------|
| `_id_to_idx` | `Dict[ID, int]` | User ID → internal row index |
| `_idx_to_id` | `Dict[int, ID]` | Internal row index → user ID |

### 3.3 Metadata

| Component | Type | Purpose |
|-----------|------|---------|
| `_metadata` | `Dict[ID, Dict[str, Any]]` | User ID → tag dictionary |

### 3.4 Free List (NEW in v2)

| Component | Type | Purpose |
|-----------|------|---------|
| `_free_list` | `List[int]` | Stack of reusable slot indices (LIFO) |

**Why free list instead of `np.where(~active)[0]` scan?**
- `np.where` is O(capacity) per insert — unacceptable for large datasets
- Free list is O(1) amortized: push on delete, pop on insert
- LIFO order improves cache locality (recently used slots tend to be hot)

### 3.5 Concurrency

- `threading.Lock` protects all mutation operations
- Reads (get, search) also acquire the lock for consistency

## 4. Algorithm Design

### 4.1 Cosine Similarity

```
cosine(q, V_i) = (V_i · q) / (||V_i|| * ||q||)
```

**Optimization**: Pre-normalize all vectors on insert. At query time, normalize query once, then compute dot product with all stored normalized vectors.

```
scores = normalized_vectors @ q_normalized
```

Range: [-1, 1], higher = more similar.

**Zero-vector handling**: Zero vectors have norm ≈ 0, normalized to zero. Dot product with zero-normalized query gives 0 similarity, which is correct (cosine similarity is undefined for zero vectors, 0 is a conservative default).

### 4.2 Euclidean Distance

```
euclidean(q, V_i) = sqrt(sum((V_i - q)²))
```

**Optimization**: Use numpy broadcasting for batch computation.

```
diffs = vectors - q
distances = np.sqrt(np.sum(diffs², axis=1))
```

Range: [0, ∞), lower = more similar. Converted to similarity by negation.

### 4.3 Top-k Selection

Use `np.argpartition` for O(n) selection (vs O(n log n) full sort), then sort only the top-k candidates.

```
top_k = np.argpartition(scores, -k)[-k:]
top_k = top_k[np.argsort(-scores[top_k])]  # sort descending
```

## 5. Filtering Strategy

### 5.1 Dict Pattern Matching (Exact Match)

```python
db.search(query, k=10, filter={"category": "science", "year": 2023})
```

Matches vectors whose tags contain **all** specified key-value pairs.

### 5.2 Callable Predicate

```python
db.search(query, k=10, filter=lambda tags: tags.get("year", 0) > 2020)
```

User-defined predicate receives the tags dict, returns True to include.

### 5.3 Filter Execution (Optimized)

**Pre-filter** (applied before similarity computation):

1. Only iterate over **active IDs** (via `_idx_to_id`), not all capacity rows
2. For each active ID, evaluate filter against metadata
3. Build boolean mask of matching indices
4. Intersect with active mask
5. Compute similarity only on matching subset

**Optimization rationale**: Skip inactive slots during filter evaluation.
For sparse deletions, this avoids scanning large swaths of empty rows.
For dense active sets, the iteration count equals `_size` rather than `_capacity`.

## 6. Growth Strategy

| Aspect | Detail |
|--------|--------|
| **Initial capacity** | Configurable (default 1024) |
| **Growth factor** | 1.5x, minimum increment 1024 |
| **Allocation method** | `np.empty` + explicit copy (safe) |
| **Slot reuse** | Free list (LIFO stack), O(1) amortized |

**Why `np.empty` + copy instead of `np.resize`?**
`np.resize` can return non-contiguous views or re-stride the array,
potentially corrupting data when the original memory can't be extended in-place.
`np.empty` + explicit copy guarantees a fresh contiguous array with no data loss risk.

## 7. Thread Safety

- Single `threading.Lock` (reentrant not needed)
- Acquired on: `insert`, `upsert`, `delete`, `search`, `get`, `clear`, `list_ids`
- All internal methods assume lock is held by caller

## 8. Exception Safety (NEW in v2)

Insert and upsert operations implement **rollback on failure**:

1. Slot is allocated before mutation begins
2. If any operation in the mutation block raises (e.g., memory error):
   - The slot is returned to the free list
   - Any partial dictionary entries are cleaned up
   - The exception is re-raised (no silent swallowing)
3. This ensures the database is never left in an inconsistent state

## 9. NaN/Inf Handling (NEW in v2)

- `_validate_vector` checks `np.all(np.isfinite(arr))` and raises `ValueError` if NaN/inf found
- Zero vectors (norm < 1e-12) are handled explicitly: normalized to zero
- Query vectors also go through validation, preventing NaN propagation

## 10. API Reference

### `VectorDB(dim: int, initial_capacity: int = 1024)`

Initialize database with given dimensionality.

### `insert(id, vector, tags=None)`

Insert a new vector. Raises `ValueError` if ID exists or vector contains NaN/inf.

### `upsert(id, vector, tags=None)`

Insert or update. Replaces vector/tags if ID exists.

### `search(query, k=10, metric='cosine', filter=None) -> List[Tuple[ID, float]]`

Search for k nearest neighbors. Returns `[(id, score), ...]` sorted by similarity descending.

### `delete(id) -> bool`

Delete by ID. Returns True if existed.

### `get(id) -> Optional[Dict]`

Get `{'vector': [...], 'tags': {...}}` or None.

### `clear()`

Remove all vectors.

### `list_ids() -> List[ID]`

Return all stored IDs.

## 11. Performance Characteristics

| Operation | Time Complexity | Notes |
|-----------|----------------|-------|
| insert (no grow) | O(1) amortized | Free list pop + O(d) normalization |
| insert (with grow) | O(capacity) | Amortized O(1) |
| search (cosine) | O(n·d) | Full scan, numpy BLAS |
| search (euclidean) | O(n·d) | Full scan, numpy broadcast |
| filter + search | O(n·f + m·d) | f = filter eval cost, m = matched count |
| delete | O(1) | Mark only + free list push |
| get | O(1) | Dict lookup |

**Memory**: ~8 × n × d bytes (vectors + normalized + active + overhead)

## 12. Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Duplicate insert | `ValueError` |
| Dimension mismatch | `ValueError` |
| NaN/inf in vector | `ValueError` (NEW) |
| Zero vector | Normalized to zero, no crash |
| Invalid metric | `ValueError` |
| k > n | Return all available |
| Empty DB search | Return `[]` |
| Filter matches nothing | Return `[]` |
| Delete non-existent | Return `False` |
| Get non-existent | Return `None` |
| Invalid vector type | `TypeError` |
| Invalid filter type | `TypeError` |
| Mutation failure | Rollback + re-raise (NEW) |
| Thread contention | Lock serializes access |

## 13. Design Rationale

### Why flat storage (no index)?

- Pure Python constraint rules out HNSW, IVF, etc.
- For datasets up to ~100K vectors with dim ≤ 768, brute force with numpy BLAS is fast enough (< 100ms)
- Dramatically simpler compared to index-based approaches

### Why pre-normalized vectors?

- Cosine similarity with pre-normalization reduces to a single dot product
- Avoids per-query normalization of the entire dataset
- Memory cost is 2x (raw + normalized) but computation is 2x faster for cosine

### Why free list instead of bitmap scan?

- `np.where(~active)` is O(capacity) — dominates insert cost after many deletions
- Free list is O(1) amortized with minimal memory overhead (one Python list)
- LIFO order naturally reuses recently freed slots (better cache behavior)

### Why pre-filter instead of post-filter?

- Pre-filter guarantees correct top-k results
- Post-filter could miss relevant results if filtered-out items dominate top-k
- For selective filters (matching few items), pre-filter is faster
