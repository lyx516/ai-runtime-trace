# Binary Search — Python Implementation

A clean, well-tested implementation of the **binary search algorithm** for sorted integer lists in Python.

## Function Signature

```python
def binary_search(arr: list[int], target: int) -> int:
    """Find the index of ``target`` in a sorted ascending list.

    Args:
        arr: A list of integers sorted in ascending order.
        target: The integer value to search for.

    Returns:
        The 0-based index of ``target`` in ``arr``, or -1 if not found.

    Raises:
        TypeError: If ``arr`` is not a list.
        TypeError: If ``target`` is not an int.
    """
```

## Usage Examples

### 1. Normal search — target found

```python
from binary_search import binary_search

arr = [1, 3, 5, 7, 9]
index = binary_search(arr, 5)
print(index)  # Output: 2
```

### 2. Target not found

```python
from binary_search import binary_search

arr = [1, 3, 5, 7, 9]
index = binary_search(arr, 4)
print(index)  # Output: -1
```

### 3. Empty list

```python
from binary_search import binary_search

index = binary_search([], 42)
print(index)  # Output: -1
```

### 4. List with negative numbers

```python
from binary_search import binary_search

arr = [-10, -5, 0, 5, 10]
index = binary_search(arr, -5)
print(index)  # Output: 1
```

## Algorithm

Binary search works by repeatedly dividing the search interval in half:

1. Start with `left = 0` and `right = len(arr) - 1`.
2. Calculate `mid = left + (right - left) // 2`.
3. If `arr[mid] == target`, return `mid`.
4. If `arr[mid] < target`, discard the left half (`left = mid + 1`).
5. If `arr[mid] > target`, discard the right half (`right = mid - 1`).
6. Repeat until `left > right` (target not found → return `-1`).

| Metric          | Value     |
|-----------------|-----------|
| Time complexity | O(log n)  |
| Space complexity| O(1)      |
| Method          | Iterative (no recursion) |

## Requirements

- **Python 3.8+** (uses type annotations)
- **pytest** (for running tests)

## Installation & Setup

```bash
# Clone or download the project, then install test dependencies
pip install pytest
```

## Running Tests

```bash
# From the project directory
python -m pytest test_binary_search.py -v
```

Expected output: all tests pass (✔).

## Project Structure

```
output/auto-71436299/
├── binary_search.py       # Binary search implementation
├── test_binary_search.py  # Comprehensive test suite (26+ test cases)
├── README.md              # This file
├── spec.md                # Specification document
├── plan.md                # Technical plan
└── tasks.md               # Task breakdown
```

## License

This project is provided as a code example. Use freely.
