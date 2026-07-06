"""
bubble_sort — A robust implementation of the Bubble Sort algorithm.

This module provides a pure-Python bubble sort function with:
  - Type annotations and a comprehensive docstring.
  - Optional custom comparator (key function) and reverse flag.
  - Defensive input validation (type checking, empty / single-element fast paths).
  - In-place and copy-based sorting modes.
  - Early termination optimisation (no unnecessary passes on already-sorted data).
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Optional, Sequence, TypeVar

T = TypeVar("T")


def bubble_sort(
    items: Sequence[T],
    *,
    key: Optional[Callable[[T], Any]] = None,
    reverse: bool = False,
    inplace: bool = False,
) -> list[T]:
    """Sort a sequence using the bubble sort algorithm.

    Bubble sort repeatedly steps through the list, compares adjacent elements,
    and swaps them if they are in the wrong order. The pass through the list
    is repeated until no swaps are needed, indicating the list is sorted.

    This implementation includes an **early-termination** optimisation: if a
    complete pass performs zero swaps, the algorithm exits immediately.

    Parameters
    ----------
    items : Sequence[T]
        The sequence of items to sort. Must contain at least one element.
    key : Callable[[T], Any] or None, optional
        A function that extracts a comparison key from each element.
        If ``None`` (the default), elements are compared directly.
    reverse : bool, optional
        If ``True``, the list is sorted in descending order (default ``False``).
    inplace : bool, optional
        If ``True``, the sort is performed **in-place** on a mutable copy of
        the input (e.g. when ``items`` is a ``list``). If ``False`` (default),
        a new list is returned and the original sequence is never modified.

    Returns
    -------
    list[T]
        The sorted list. If ``inplace=True`` and ``items`` is a ``list``,
        the returned list is the same object as ``items`` (now mutated).

    Raises
    ------
    TypeError
        If ``items`` is not a Sequence, or if elements cannot be ordered
        (e.g. comparing ``int`` with ``str``).
    ValueError
        If ``items`` is empty.

    Examples
    --------
    >>> bubble_sort([3, 1, 2])
    [1, 2, 3]

    >>> bubble_sort(["banana", "apple", "cherry"], reverse=True)
    ['cherry', 'banana', 'apple']

    >>> bubble_sort([(1, "z"), (2, "a")], key=lambda x: x[1])
    [(2, 'a'), (1, 'z')]

    >>> data = [5, 3, 1]
    >>> result = bubble_sort(data, inplace=True)
    >>> result is data
    True
    >>> result
    [1, 3, 5]
    """
    # --- Input validation ---------------------------------------------------
    if not isinstance(items, Sequence):
        raise TypeError(
            f"Expected a Sequence, got {type(items).__name__!r}."
        )

    if len(items) == 0:
        raise ValueError("Cannot sort an empty sequence.")

    # --- Single-element fast path -------------------------------------------
    if len(items) == 1:
        return [items[0]] if not inplace else list(items)  # type: ignore[return-value]

    # --- Prepare working copy -----------------------------------------------
    if inplace:
        if not isinstance(items, list):
            raise TypeError(
                f"inplace=True requires a list, got {type(items).__name__!r}."
            )
        arr: list[T] = items
    else:
        arr = list(items)

    n = len(arr)

    # --- Comparator helper --------------------------------------------------
    def _should_swap(a: T, b: T) -> bool:
        """Return True if *a* should come after *b* (i.e. they need swapping)."""
        ka = key(a) if key is not None else a
        kb = key(b) if key is not None else b
        return ka > kb if not reverse else ka < kb

    # --- Bubble sort (with early termination) -------------------------------
    for i in range(n):
        swapped = False
        # After each pass, the last i elements are already in their final position.
        for j in range(0, n - i - 1):
            if _should_swap(arr[j], arr[j + 1]):
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        # Early termination: if no swaps occurred, the list is sorted.
        if not swapped:
            break

    return arr
