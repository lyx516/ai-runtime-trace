"""Tests for bubble_sort.py — covers normal cases, edge cases, and errors."""

import pytest

from bubble_sort import bubble_sort


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestNormalCases:
    """Standard sorting scenarios."""

    def test_sorted_ascending(self):
        assert bubble_sort([1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]

    def test_reverse_sorted(self):
        assert bubble_sort([5, 4, 3, 2, 1]) == [1, 2, 3, 4, 5]

    def test_random_order(self):
        assert bubble_sort([3, 1, 4, 1, 5, 9, 2, 6]) == [1, 1, 2, 3, 4, 5, 6, 9]

    def test_duplicates(self):
        assert bubble_sort([4, 2, 4, 2, 4]) == [2, 2, 4, 4, 4]

    def test_negative_numbers(self):
        assert bubble_sort([0, -5, 3, -1, 2]) == [-5, -1, 0, 2, 3]

    def test_floats(self):
        assert bubble_sort([3.2, 1.1, 2.2]) == [1.1, 2.2, 3.2]

    def test_strings(self):
        assert bubble_sort(["banana", "apple", "cherry"]) == [
            "apple",
            "banana",
            "cherry",
        ]

    def test_mixed_numeric_types(self):
        # int and float are comparable in Python
        assert bubble_sort([3, 1.5, 2]) == [1.5, 2, 3]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary and degenerate inputs."""

    def test_empty_list(self):
        assert bubble_sort([]) == []

    def test_single_element(self):
        assert bubble_sort([42]) == [42]

    def test_two_elements_sorted(self):
        assert bubble_sort([1, 2]) == [1, 2]

    def test_two_elements_unsorted(self):
        assert bubble_sort([2, 1]) == [1, 2]

    def test_all_equal(self):
        assert bubble_sort([7, 7, 7, 7]) == [7, 7, 7, 7]


# ---------------------------------------------------------------------------
# Reverse flag
# ---------------------------------------------------------------------------

class TestReverse:
    """Descending-order sorting."""

    def test_reverse_ascending(self):
        assert bubble_sort([1, 2, 3], reverse=True) == [3, 2, 1]

    def test_reverse_descending(self):
        assert bubble_sort([3, 2, 1], reverse=True) == [3, 2, 1]

    def test_reverse_random(self):
        assert bubble_sort([3, 1, 4, 2], reverse=True) == [4, 3, 2, 1]

    def test_reverse_empty(self):
        assert bubble_sort([], reverse=True) == []

    def test_reverse_single(self):
        assert bubble_sort([99], reverse=True) == [99]


# ---------------------------------------------------------------------------
# Key function
# ---------------------------------------------------------------------------

class TestKey:
    """Sorting by a computed key."""

    def test_key_string_length(self):
        data = ["aaa", "b", "cc"]
        assert bubble_sort(data, key=len) == ["b", "cc", "aaa"]

    def test_key_negate(self):
        data = [1, 2, 3, 4]
        assert bubble_sort(data, key=lambda x: -x) == [4, 3, 2, 1]

    def test_key_with_reverse(self):
        data = ["aaa", "b", "cc"]
        assert bubble_sort(data, key=len, reverse=True) == ["aaa", "cc", "b"]

    def test_key_tuple_access(self):
        data = [(1, "z"), (2, "a"), (1, "a")]
        # Sort by first element, then second
        assert bubble_sort(data, key=lambda x: (x[0], x[1])) == [
            (1, "a"),
            (1, "z"),
            (2, "a"),
        ]


# ---------------------------------------------------------------------------
# In-place behaviour
# ---------------------------------------------------------------------------

class TestInPlace:
    """Verify the list is sorted in-place (same object)."""

    def test_same_object(self):
        original = [3, 1, 2]
        result = bubble_sort(original)
        assert result is original

    def test_mutation_visible(self):
        original = [3, 1, 2]
        bubble_sort(original)
        assert original == [1, 2, 3]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    """Invalid inputs should raise appropriate exceptions."""

    def test_none_raises(self):
        with pytest.raises(ValueError, match="must not be None"):
            bubble_sort(None)  # type: ignore[arg-type]

    def test_not_a_list_tuple(self):
        with pytest.raises(TypeError, match="expected a list"):
            bubble_sort((3, 1, 2))  # type: ignore[arg-type]

    def test_not_a_list_dict(self):
        with pytest.raises(TypeError, match="expected a list"):
            bubble_sort({"a": 1})  # type: ignore[arg-type]

    def test_key_not_callable(self):
        with pytest.raises(TypeError, match="key must be callable"):
            bubble_sort([1, 2, 3], key=42)  # type: ignore[arg-type]

    def test_incomparable_elements(self):
        with pytest.raises(TypeError):
            bubble_sort([1, "two", 3])


# ---------------------------------------------------------------------------
# Stability (bubble sort is stable)
# ---------------------------------------------------------------------------

class TestStability:
    """Bubble sort preserves the relative order of equal elements."""

    def test_stable(self):
        pairs = [(1, "a"), (2, "b"), (1, "c")]
        # Sort by first element only — (1,'a') should stay before (1,'c')
        result = bubble_sort(pairs, key=lambda x: x[0])
        assert result == [(1, "a"), (1, "c"), (2, "b")]
