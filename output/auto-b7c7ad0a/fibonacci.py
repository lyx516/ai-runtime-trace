"""
斐波那契数列实现模块。

提供多种方式计算斐波那契数列，包括：
- fib_recursive: 递归实现（带记忆化）
- fib_iterative: 迭代实现
- fib_generator: 生成器实现
- fib_matrix: 矩阵快速幂实现
- fib_sequence: 生成前 n 个斐波那契数

所有函数都包含完整的类型注解、文档字符串和错误处理。
"""

from functools import lru_cache
from typing import Generator, List, Union


# ──────────────────────────────────────────────
# 公共异常
# ──────────────────────────────────────────────

class FibonacciError(Exception):
    """斐波那契计算相关的基类异常。"""


class InvalidInputError(FibonacciError, ValueError):
    """输入参数无效时抛出。"""


# ──────────────────────────────────────────────
# 核心实现
# ──────────────────────────────────────────────

@lru_cache(maxsize=None)
def fib_recursive(n: int) -> int:
    """
    使用带记忆化的递归计算第 n 个斐波那契数。

    时间复杂度 O(n)，空间复杂度 O(n)（递归栈 + 缓存）。

    Parameters
    ----------
    n : int
        非负整数，表示斐波那契数列的索引（从 0 开始）。

    Returns
    -------
    int
        第 n 个斐波那契数。

    Raises
    ------
    InvalidInputError
        当 n 为负数时抛出。

    Examples
    --------
    >>> fib_recursive(0)
    0
    >>> fib_recursive(1)
    1
    >>> fib_recursive(10)
    55
    """
    _validate_non_negative(n)
    if n < 2:
        return n
    return fib_recursive(n - 1) + fib_recursive(n - 2)


def fib_iterative(n: int) -> int:
    """
    使用迭代计算第 n 个斐波那契数。

    时间复杂度 O(n)，空间复杂度 O(1)。

    Parameters
    ----------
    n : int
        非负整数，表示斐波那契数列的索引（从 0 开始）。

    Returns
    -------
    int
        第 n 个斐波那契数。

    Raises
    ------
    InvalidInputError
        当 n 为负数时抛出。

    Examples
    --------
    >>> fib_iterative(0)
    0
    >>> fib_iterative(1)
    1
    >>> fib_iterative(10)
    55
    """
    _validate_non_negative(n)
    if n < 2:
        return n

    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def fib_generator() -> Generator[int, None, None]:
    """
    生成无限斐波那契数列的生成器。

    从 F(0) = 0, F(1) = 1 开始无限生成后续斐波那契数。

    Yields
    ------
    int
        下一个斐波那契数。

    Examples
    --------
    >>> gen = fib_generator()
    >>> [next(gen) for _ in range(10)]
    [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    """
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b


def fib_matrix(n: int) -> int:
    """
    使用矩阵快速幂计算第 n 个斐波那契数。

    时间复杂度 O(log n)，空间复杂度 O(log n)（递归栈）。

    Parameters
    ----------
    n : int
        非负整数，表示斐波那契数列的索引（从 0 开始）。

    Returns
    -------
    int
        第 n 个斐波那契数。

    Raises
    ------
    InvalidInputError
        当 n 为负数时抛出。

    Examples
    --------
    >>> fib_matrix(0)
    0
    >>> fib_matrix(1)
    1
    >>> fib_matrix(10)
    55
    >>> fib_matrix(50)
    12586269025
    """
    _validate_non_negative(n)
    if n < 2:
        return n

    def _matrix_mult(a: List[List[int]], b: List[List[int]]) -> List[List[int]]:
        """2x2 矩阵乘法。"""
        return [
            [a[0][0] * b[0][0] + a[0][1] * b[1][0],
             a[0][0] * b[0][1] + a[0][1] * b[1][1]],
            [a[1][0] * b[0][0] + a[1][1] * b[1][0],
             a[1][0] * b[0][1] + a[1][1] * b[1][1]],
        ]

    def _matrix_pow(mat: List[List[int]], power: int) -> List[List[int]]:
        """矩阵快速幂。"""
        if power == 1:
            return mat
        if power % 2 == 0:
            half = _matrix_pow(mat, power // 2)
            return _matrix_mult(half, half)
        return _matrix_mult(mat, _matrix_pow(mat, power - 1))

    base = [[1, 1], [1, 0]]
    result = _matrix_pow(base, n)
    return result[0][1]


def fib_sequence(n: int) -> List[int]:
    """
    返回前 n 个斐波那契数组成的列表。

    Parameters
    ----------
    n : int
        非负整数，表示要生成的斐波那契数的个数。

    Returns
    -------
    List[int]
        包含前 n 个斐波那契数的列表。

    Raises
    ------
    InvalidInputError
        当 n 为负数时抛出。

    Examples
    --------
    >>> fib_sequence(0)
    []
    >>> fib_sequence(1)
    [0]
    >>> fib_sequence(5)
    [0, 1, 1, 2, 3]
    """
    _validate_non_negative(n)
    gen = fib_generator()
    return [next(gen) for _ in range(n)]


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _validate_non_negative(n: int) -> None:
    """
    验证输入是否为非负整数。

    Parameters
    ----------
    n : int
        待验证的输入。

    Raises
    ------
    InvalidInputError
        当 n 不是 int 类型或为负数时抛出。
    """
    if not isinstance(n, int):
        raise InvalidInputError(f"输入必须为整数，收到 {type(n).__name__}: {n!r}")
    if n < 0:
        raise InvalidInputError(f"输入必须为非负整数，收到: {n}")


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

def main() -> None:
    """命令行入口，计算并打印第 n 个斐波那契数。"""
    import argparse

    parser = argparse.ArgumentParser(description="计算斐波那契数列")
    parser.add_argument(
        "n",
        type=int,
        help="斐波那契数列的索引（非负整数）",
    )
    parser.add_argument(
        "--method",
        choices=["iterative", "recursive", "matrix"],
        default="iterative",
        help="计算方法（默认: iterative）",
    )
    parser.add_argument(
        "--sequence",
        action="store_true",
        help="输出前 n 个斐波那契数而非第 n 个",
    )

    args = parser.parse_args()

    try:
        if args.sequence:
            result = fib_sequence(args.n)
            print(result)
        else:
            methods = {
                "iterative": fib_iterative,
                "recursive": fib_recursive,
                "matrix": fib_matrix,
            }
            result = methods[args.method](args.n)
            print(result)
    except InvalidInputError as e:
        print(f"错误: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
