"""Binary search implementation for sorted lists.

This module provides a single function `binary_search` that performs
binary search on a sorted (ascending) integer list.
"""


def binary_search(arr: list[int], target: int) -> int:
    """Find the index of ``target`` in a sorted ascending list.

    Performs an iterative binary search (O(log n) time, O(1) space).
    If the target appears multiple times, any matching index may be returned.

    Args:
        arr: A list of integers sorted in ascending order.
        target: The integer value to search for.

    Returns:
        The 0-based index of ``target`` in ``arr``, or -1 if not found.

    Raises:
        TypeError: If ``arr`` is not a list.
        TypeError: If ``target`` is not an int.
    """
    if not isinstance(arr, list):
        raise TypeError("arr must be a list")

    if not isinstance(target, int):
        raise TypeError("target must be an int")

    left, right = 0, len(arr) - 1

    while left <= right:
        # Use left + (right - left) // 2 to avoid potential overflow
        # (idiomatic even though Python ints have no overflow).
        mid = left + (right - left) // 2
        mid_value = arr[mid]

        if mid_value == target:
            return mid
        if mid_value < target:
            left = mid + 1
        else:
            right = mid - 1

    return -1
