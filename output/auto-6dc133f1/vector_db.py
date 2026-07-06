"""
vector_db.py — A lightweight embedded vector database with numpy acceleration.

Supports:
- Cosine similarity and Euclidean distance search
- Metadata (tags) filtering with dict exact-match or callable predicate
- Thread-safe insert/delete/search operations
- Free-list based slot reuse (O(1) amortized)
- Safe growth via np.empty + manual copy (no data loss risk)

Usage:
    db = VectorDB(dim=128)
    db.insert("doc1", [0.1]*128, tags={"category": "science"})
    results = db.search([0.2]*128, k=5, metric="cosine")
"""

import math
import numpy as np
import threading
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

# Type aliases
Vector = Sequence[float]
ID = Union[int, str]
TagFilter = Optional[Union[Dict[str, Any], Callable[[Dict[str, Any]], bool]]]


class VectorDB:
    """An in-memory vector database with metadata filtering.

    Stores vectors as a numpy array and supports fast similarity search
    via vectorized operations. Thread-safe for concurrent access.

    Design highlights:
    - Free list for O(1) slot allocation (amortized)
    - Safe array growth via np.empty + explicit copy
    - Pre-normalized vectors for fast cosine search
    - Exception-safe mutations with rollback on failure
    - Proper NaN/inf handling in vectors and norms
    """

    def __init__(self, dim: int, initial_capacity: int = 1024):
        """Initialize the vector database.

        Args:
            dim: Dimensionality of vectors to store.
            initial_capacity: Pre-allocated row count for the numpy array.
                             Grows automatically when exceeded.

        Raises:
            ValueError: If dim <= 0 or initial_capacity <= 0.
        """
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        if initial_capacity <= 0:
            raise ValueError(
                f"initial_capacity must be positive, got {initial_capacity}"
            )

        self._dim = dim
        self._capacity = initial_capacity

        # Storage: pre-allocate numpy arrays (filled later on insert)
        self._vectors = np.empty((initial_capacity, dim), dtype=np.float32)
        self._normalized = np.empty((initial_capacity, dim), dtype=np.float32)

        # ID management
        self._id_to_idx: Dict[ID, int] = {}
        self._idx_to_id: Dict[int, ID] = {}

        # Metadata
        self._metadata: Dict[ID, Dict[str, Any]] = {}

        # Deletion tracking (mask: True = active, False = deleted/empty)
        self._active = np.zeros(initial_capacity, dtype=bool)

        # Free list: stack of reusable slot indices (LIFO for cache locality)
        self._free_list: List[int] = []

        # Current count of active vectors
        self._size = 0

        # Concurrency lock
        self._lock = threading.Lock()

    # ---- Public API ----

    @property
    def dim(self) -> int:
        """Return the dimensionality of vectors in this database."""
        return self._dim

    @property
    def size(self) -> int:
        """Return the number of vectors currently stored."""
        return self._size

    def insert(
        self,
        id: ID,
        vector: Vector,
        tags: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a vector with optional metadata tags.

        Args:
            id: Unique identifier for the vector.
            vector: The vector data as a sequence of floats.
            tags: Optional dictionary of metadata key-value pairs.

        Raises:
            ValueError: If the ID already exists, or vector dimension
                       doesn't match, or vector contains NaN/inf.
            TypeError: If vector is not a sequence of numbers.
        """
        vec = self._validate_vector(vector)

        with self._lock:
            if id in self._id_to_idx:
                raise ValueError(
                    f"ID '{id}' already exists. Use upsert() to update."
                )

            idx = self._allocate_slot()

            # Compute norm — may raise ValueError for NaN/inf
            norm = np.linalg.norm(vec)

            # --- mutation point: begin (rollback on failure) ---
            try:
                self._vectors[idx] = vec
                if norm > 1e-12:
                    self._normalized[idx] = vec / norm
                else:
                    # Zero vector: normalized stays zero
                    self._normalized[idx] = 0.0
                self._active[idx] = True
                self._id_to_idx[id] = idx
                self._idx_to_id[idx] = id
                self._metadata[id] = tags.copy() if tags else {}
                self._size += 1
            except Exception:
                # Rollback: undo partial state changes
                self._active[idx] = False
                self._free_list.append(idx)
                if id in self._id_to_idx:
                    del self._id_to_idx[id]
                if idx in self._idx_to_id:
                    del self._idx_to_id[idx]
                if id in self._metadata:
                    del self._metadata[id]
                raise

    def upsert(
        self,
        id: ID,
        vector: Vector,
        tags: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a vector by ID.

        If the ID exists, replaces its vector and tags.
        If not, inserts a new entry.

        Args:
            id: Unique identifier for the vector.
            vector: The vector data as a sequence of floats.
            tags: Optional dictionary of metadata key-value pairs.

        Raises:
            ValueError: If vector dimension doesn't match, or vector
                       contains NaN/inf.
            TypeError: If vector is not a sequence of numbers.
        """
        vec = self._validate_vector(vector)

        with self._lock:
            if id in self._id_to_idx:
                # Update in-place
                idx = self._id_to_idx[id]
                norm = np.linalg.norm(vec)
                self._vectors[idx] = vec
                if norm > 1e-12:
                    self._normalized[idx] = vec / norm
                else:
                    self._normalized[idx] = 0.0
                self._metadata[id] = tags.copy() if tags else {}
            else:
                # Insert new
                idx = self._allocate_slot()
                norm = np.linalg.norm(vec)
                try:
                    self._vectors[idx] = vec
                    if norm > 1e-12:
                        self._normalized[idx] = vec / norm
                    else:
                        self._normalized[idx] = 0.0
                    self._active[idx] = True
                    self._id_to_idx[id] = idx
                    self._idx_to_id[idx] = id
                    self._metadata[id] = tags.copy() if tags else {}
                    self._size += 1
                except Exception:
                    self._active[idx] = False
                    self._free_list.append(idx)
                    if id in self._id_to_idx:
                        del self._id_to_idx[id]
                    if idx in self._idx_to_id:
                        del self._idx_to_id[idx]
                    if id in self._metadata:
                        del self._metadata[id]
                    raise

    def search(
        self,
        query: Vector,
        k: int = 10,
        metric: str = "cosine",
        filter: Optional[TagFilter] = None,
    ) -> List[Tuple[ID, float]]:
        """Search for the k nearest neighbors of the query vector.

        Args:
            query: Query vector as a sequence of floats.
            k: Number of results to return (default 10).
            metric: Distance metric — 'cosine' or 'euclidean' (default 'cosine').
            filter: Optional filter. Can be:
                - A dict: matches vectors whose tags contain all key-value pairs.
                - A callable: receives tags dict, returns True to include.

        Returns:
            List of (id, score) tuples sorted by similarity (most similar first).
            For 'cosine', score is cosine similarity in [-1, 1] (higher = better).
            For 'euclidean', score is negative distance (higher = better).

        Raises:
            ValueError: If metric is not 'cosine' or 'euclidean'.
            TypeError: If query is not a valid sequence of numbers.
        """
        q = self._validate_vector(query)

        with self._lock:
            if self._size == 0:
                return []

            # Get active indices
            active_mask = self._active.copy()

            # Apply metadata filter if provided
            if filter is not None:
                filter_mask = self._build_filter_mask(filter)
                active_mask = active_mask & filter_mask

            active_indices = np.where(active_mask)[0]
            n_active = len(active_indices)

            if n_active == 0:
                return []

            # Compute similarity/distance
            if metric == "cosine":
                q_norm_val = np.linalg.norm(q)
                if q_norm_val > 1e-12:
                    q_norm = q / q_norm_val
                else:
                    q_norm = q  # zero query → zero normalized
                scores = self._normalized[active_indices] @ q_norm
                # scores are cosine similarity in [-1, 1], higher = better
            elif metric == "euclidean":
                diffs = self._vectors[active_indices] - q
                distances = np.sqrt(np.sum(diffs ** 2, axis=1))
                # Convert to similarity: negative distance, higher = better
                scores = -distances
            else:
                raise ValueError(
                    f"Unknown metric '{metric}'. Use 'cosine' or 'euclidean'."
                )

            # Get top-k indices
            k_actual = min(k, n_active)
            # For both metrics, higher score = more similar
            top_k_local = np.argpartition(scores, -k_actual)[-k_actual:]
            # Sort top-k by score descending
            top_k_local = top_k_local[np.argsort(-scores[top_k_local])]

            results = []
            for local_idx in top_k_local:
                global_idx = active_indices[local_idx]
                vid = self._idx_to_id[global_idx]
                results.append((vid, float(scores[local_idx])))

            return results

    def delete(self, id: ID) -> bool:
        """Delete a vector by ID.

        Args:
            id: The identifier of the vector to delete.

        Returns:
            True if the vector existed and was deleted, False otherwise.
        """
        with self._lock:
            if id not in self._id_to_idx:
                return False

            idx = self._id_to_idx[id]
            self._active[idx] = False
            self._free_list.append(idx)
            del self._id_to_idx[id]
            del self._idx_to_id[idx]
            if id in self._metadata:
                del self._metadata[id]
            self._size -= 1
            return True

    def get(self, id: ID) -> Optional[Dict[str, Any]]:
        """Retrieve a vector and its metadata by ID.

        Args:
            id: The identifier of the vector.

        Returns:
            A dict with keys 'vector' (list of floats) and 'tags' (dict),
            or None if the ID doesn't exist.
        """
        with self._lock:
            if id not in self._id_to_idx:
                return None

            idx = self._id_to_idx[id]
            return {
                "vector": self._vectors[idx].tolist(),
                "tags": self._metadata.get(id, {}).copy(),
            }

    def clear(self) -> None:
        """Remove all vectors from the database."""
        with self._lock:
            self._vectors = np.empty((self._capacity, self._dim), dtype=np.float32)
            self._normalized = np.empty((self._capacity, self._dim), dtype=np.float32)
            self._active[:] = False
            self._id_to_idx.clear()
            self._idx_to_id.clear()
            self._metadata.clear()
            self._free_list.clear()
            self._size = 0

    def list_ids(self) -> List[ID]:
        """Return a list of all stored IDs."""
        with self._lock:
            return list(self._id_to_idx.keys())

    # ---- Internal Methods ----

    def _validate_vector(self, vector: Vector) -> np.ndarray:
        """Validate and convert input to numpy float32 array.

        Args:
            vector: Input vector.

        Returns:
            Numpy float32 array of shape (dim,).

        Raises:
            TypeError: If vector is not a sequence of numbers.
            ValueError: If dimension doesn't match or vector contains NaN/inf.
        """
        try:
            arr = np.asarray(vector, dtype=np.float32)
        except (ValueError, TypeError) as e:
            raise TypeError(
                f"Vector must be a sequence of numbers, got {type(vector)}"
            ) from e

        if arr.ndim != 1:
            raise ValueError(
                f"Vector must be 1-dimensional, got {arr.ndim} dimensions"
            )
        if arr.shape[0] != self._dim:
            raise ValueError(
                f"Vector dimension {arr.shape[0]} does not match "
                f"database dimension {self._dim}"
            )

        # Check for NaN or infinity values
        if not np.all(np.isfinite(arr)):
            raise ValueError(
                "Vector contains NaN or infinity values, which are not supported"
            )

        return arr

    def _allocate_slot(self) -> int:
        """Find or create a slot for a new vector.

        Uses a free list (stack) for O(1) amortized slot reuse.
        Falls back to growing the array when no free slots exist.

        Returns:
            Index of the allocated slot.
        """
        # Reuse a freed slot if available (LIFO for cache locality)
        if self._free_list:
            return self._free_list.pop()

        # No free slots — grow the array
        if self._size >= self._capacity:
            self._grow()

        # Use the next sequential slot
        idx = self._size
        return idx

    def _grow(self) -> None:
        """Grow internal storage arrays.

        Uses 1.5x growth factor with a minimum increment of 1024.
        Uses np.empty + explicit copy for safe growth (no data loss risk
        unlike np.resize which may re-stride and corrupt data).
        """
        old_capacity = self._capacity
        new_capacity = max(old_capacity + 1024, int(old_capacity * 1.5))

        # Safe growth: allocate new arrays, copy data, swap references
        new_vectors = np.empty((new_capacity, self._dim), dtype=np.float32)
        new_normalized = np.empty((new_capacity, self._dim), dtype=np.float32)
        new_active = np.empty(new_capacity, dtype=bool)

        # Copy existing data
        new_vectors[:old_capacity] = self._vectors[:old_capacity]
        new_normalized[:old_capacity] = self._normalized[:old_capacity]
        new_active[:old_capacity] = self._active[:old_capacity]

        # Zero-initialize new rows (redundant for empty, but explicit for safety)
        new_vectors[old_capacity:] = 0
        new_normalized[old_capacity:] = 0
        new_active[old_capacity:] = False

        # Swap references
        self._vectors = new_vectors
        self._normalized = new_normalized
        self._active = new_active
        self._capacity = new_capacity

    def _build_filter_mask(self, filter: TagFilter) -> np.ndarray:
        """Build a boolean mask for vectors matching the filter.

        Optimized strategy:
        - For dict filters with many entries: pre-compute tag lookup arrays
          to minimize Python iteration overhead.
        - For callable filters: iterate active IDs (not all capacity).

        Args:
            filter: Dict (exact match) or callable (predicate).

        Returns:
            Boolean numpy array of shape (capacity,).

        Raises:
            TypeError: If filter is neither dict nor callable.
        """
        mask = np.zeros(self._capacity, dtype=bool)

        if isinstance(filter, dict):
            if not filter:
                # Empty dict matches everything
                mask[:] = self._active
                return mask

            # Dict mode: exact match on all key-value pairs
            # Only iterate over active IDs (not all capacity rows)
            for idx, vid in list(self._idx_to_id.items()):
                if not self._active[idx]:
                    continue
                tags = self._metadata.get(vid, {})
                if all(tags.get(k) == v for k, v in filter.items()):
                    mask[idx] = True

        elif callable(filter):
            # Callable mode: predicate receives tags dict
            for idx, vid in list(self._idx_to_id.items()):
                if not self._active[idx]:
                    continue
                tags = self._metadata.get(vid, {})
                if filter(tags):
                    mask[idx] = True

        else:
            raise TypeError(
                f"filter must be a dict or callable, got {type(filter)}"
            )

        return mask
