"""Unit tests for binary_search function.

Covers all examples, boundary conditions, error handling, and performance
as specified in spec.md.
"""

import time

import pytest

from binary_search import binary_search

# =========================================================================
# Tests for examples (spec §4.3)
# =========================================================================

EXAMPLE_CASES = [
    # (arr, target, expected_index)
    ([1, 3, 5, 7, 9], 5, 2),        # middle element
    ([1, 3, 5, 7, 9], 1, 0),        # first element
    ([1, 3, 5, 7, 9], 9, 4),        # last element
    ([1, 3, 5, 7, 9], 4, -1),       # not found
    ([], 1, -1),                     # empty list
    ([-5, -3, 0, 2], -3, 1),        # negative numbers
    ([10], 10, 0),                  # single element, match
    ([10], 5, -1),                  # single element, no match
]


@pytest.mark.parametrize("arr, target, expected", EXAMPLE_CASES)
def test_examples(arr: list[int], target: int, expected: int) -> None:
    """All example cases from spec §4.3 must return the expected index."""
    assert binary_search(arr, target) == expected


# =========================================================================
# Tests for duplicate values (spec FR-02, BC-08)
# =========================================================================

DUPLICATE_CASES = [
    ([2, 2, 2], 2),
    ([1, 1, 2, 3], 1),
    ([1, 2, 2, 2, 3], 2),
    ([5, 5, 5, 5, 5], 5),
]


@pytest.mark.parametrize("arr, target", DUPLICATE_CASES)
def test_duplicate_values(arr: list[int], target: int) -> None:
    """With duplicates, the returned index must point to the target value."""
    result = binary_search(arr, target)
    assert 0 <= result < len(arr), f"Index {result} out of range for list of length {len(arr)}"
    assert arr[result] == target, f"arr[{result}] = {arr[result]}, expected {target}"


# =========================================================================
# Tests for boundary conditions (spec §3)
# =========================================================================

BOUNDARY_CASES = [
    # (arr, target, expected)  — description
    ([], 42, -1),                          # BC-01: empty list
    ([7], 7, 0),                           # BC-02: single element, match
    ([7], 3, -1),                          # BC-03: single element, no match
    ([1, 3, 5, 7, 9], 1, 0),              # BC-04: target at start (index 0)
    ([1, 3, 5, 7, 9], 9, 4),              # BC-05: target at end (index len-1)
    ([1, 3, 5, 7, 9], 0, -1),             # BC-06: target smaller than all
    ([1, 3, 5, 7, 9], 10, -1),            # BC-07: target larger than all
    ([-10, -5, 0, 5, 10], -5, 1),         # BC-09: negative target
    ([42], 42, 0),                         # BC-10: minimal valid length, match
    ([42], 99, -1),                        # BC-10: minimal valid length, no match
]


@pytest.mark.parametrize("arr, target, expected", BOUNDARY_CASES)
def test_boundary_conditions(arr: list[int], target: int, expected: int) -> None:
    """All boundary conditions from spec §3 must be satisfied."""
    assert binary_search(arr, target) == expected


# =========================================================================
# Tests for error handling (spec §6)
# =========================================================================


class TestErrorHandling:
    """Error handling scenarios from spec §6."""

    def test_arr_is_none(self) -> None:
        """EH-01: arr=None raises TypeError."""
        with pytest.raises(TypeError, match="arr must be a list"):
            binary_search(None, 5)  # type: ignore[arg-type]

    def test_arr_not_list(self) -> None:
        """EH-02: arr as non-list raises TypeError."""
        with pytest.raises(TypeError, match="arr must be a list"):
            binary_search("not a list", 5)  # type: ignore[arg-type]

    def test_arr_is_dict(self) -> None:
        """EH-02 variant: dict is also not a list."""
        with pytest.raises(TypeError, match="arr must be a list"):
            binary_search({"a": 1}, 5)  # type: ignore[arg-type]

    def test_arr_is_int(self) -> None:
        """EH-02 variant: int is not a list."""
        with pytest.raises(TypeError, match="arr must be a list"):
            binary_search(12345, 5)  # type: ignore[arg-type]

    def test_target_not_int(self) -> None:
        """EH-03: target as non-int raises TypeError."""
        with pytest.raises(TypeError, match="target must be an int"):
            binary_search([1, 2, 3], "not an int")  # type: ignore[arg-type]

    def test_target_is_float(self) -> None:
        """EH-03 variant: float is not an int."""
        with pytest.raises(TypeError, match="target must be an int"):
            binary_search([1, 2, 3], 3.14)  # type: ignore[arg-type]


# =========================================================================
# Performance test (spec AC-11)
# =========================================================================


class TestPerformance:
    """Performance requirements from spec §7.3."""

    def test_large_list_performance(self) -> None:
        """Search on a list of 10^6 elements must complete in < 0.1 seconds."""
        n = 10**6
        large_arr = list(range(n))
        target = n - 1  # worst-case: last element

        start = time.time()
        result = binary_search(large_arr, target)
        elapsed = time.time() - start

        assert result == target, f"Expected {target}, got {result}"
        assert elapsed < 0.1, f"Performance threshold exceeded: {elapsed:.4f}s > 0.1s"

    def test_large_list_not_found(self) -> None:
        """Search for a missing value in a large list must be fast."""
        n = 10**6
        large_arr = list(range(n))
        target = -1  # not present

        start = time.time()
        result = binary_search(large_arr, target)
        elapsed = time.time() - start

        assert result == -1
        assert elapsed < 0.1, f"Performance threshold exceeded: {elapsed:.4f}s > 0.1s"
