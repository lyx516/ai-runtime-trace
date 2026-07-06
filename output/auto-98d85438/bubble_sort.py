"""
bubble_sort.py — A clean implementation of the Bubble Sort algorithm.

Provides a single public function `bubble_sort` that sorts a list of
comparable elements in-place using the classic bubble sort algorithm.
Includes comprehensive type annotations, input validation, and edge-case
handling.
"""

from __future__ import annotations

from typing import List, Optional, TypeVar

T = TypeVar("T")


def bubble_sort(
    items: List[T],
    *,
    reverse: bool = False,
    key: Optional[callable] = None,
) -> List[T]:
    """Sort *items* in-place using the bubble sort algorithm and return it.

    Bubble sort repeatedly steps through the list, compares adjacent
    elements, and swaps them if they are in the wrong order. The pass
    through the list is repeated until no swaps are needed.

    Parameters
    ----------
    items : list
        The list of comparable elements to sort.  The list is modified
        in-place.
    reverse : bool, optional
        If ``True``, sort in descending order (default ``False``).
    key : callable, optional
        A function that extracts a comparison key from each element.
        If ``None`` (the default), elements are compared directly.

    Returns
    -------
    list
        The sorted list (same object as *items*).

    Raises
    ------
    TypeError
        If *items* is not a list, or if elements cannot be ordered
        (e.g. ``int`` vs ``str``), or if *key* is not callable.
    ValueError
        If *items* is ``None``.

    Examples
    --------
    >>> bubble_sort([3, 1, 2])
    [1, 2, 3]

    >>> bubble_sort([3, 1, 2], reverse=True)
    [3, 2, 1]

    >>> bubble_sort([(1, 'z'), (2, 'a')], key=lambda x: x[1])
    [(2, 'a'), (1, 'z')]

    >>> bubble_sort([])
    []

    >>> bubble_sort([42])
    [42]
    """
    # --- input validation ------------------------------------------------
    if items is None:
        raise ValueError("items must not be None")
    if not isinstance(items, list):
        raise TypeError(f"expected a list, got {type(items).__name__}")
    if key is not None and not callable(key):
        raise TypeError(f"key must be callable, got {type(key).__name__}")

    # --- early-exit for trivially sorted lists ---------------------------
    n = len(items)
    if n <= 1:
        return items

    # --- bubble sort core ------------------------------------------------
    # Build the comparison helper once to avoid per-element branching.
    if key is None:
        if reverse:

            def _out_of_order(a: T, b: T) -> bool:
                return a < b  # descending: swap when left < right

        else:

            def _out_of_order(a: T, b: T) -> bool:
                return a > b  # ascending:  swap when left > right

    else:

        if reverse:

            def _out_of_order(a: T, b: T) -> bool:
                return key(a) < key(b)

        else:

            def _out_of_order(a: T, b: T) -> bool:
                return key(a) > key(b)

    for i in range(n):
        swapped = False
        # After each pass the largest (or smallest) element has bubbled to
        # position n-1-i, so we can stop one element earlier each time.
        for j in range(0, n - 1 - i):
            if _out_of_order(items[j], items[j + 1]):
                items[j], items[j + 1] = items[j + 1], items[j]
                swapped = True
        # If no swaps happened during the entire pass the list is sorted.
        if not swapped:
            break

    return items
