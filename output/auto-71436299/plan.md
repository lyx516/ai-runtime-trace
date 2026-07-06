# 二分查找函数 — 技术方案与实施计划 (Plan)

## 1. 概述

本文档基于 [spec.md](./spec.md) 制定技术方案。项目目标是实现一个 Python 二分查找函数 `binary_search`，附带完整的单元测试和 README 文档。

## 2. 架构设计

### 2.1 组件划分

本项目规模小，按单一职责原则划分为 3 个组件：

| 组件 | 文件 | 职责 |
|------|------|------|
| **核心函数** | `binary_search.py` | 实现二分查找算法，包含类型注解、docstring、参数校验 |
| **单元测试** | `test_binary_search.py` | 覆盖 spec 中所有示例、边界条件、错误处理、性能测试 |
| **使用文档** | `README.md` | 介绍函数功能、用法示例、安装运行说明 |

### 2.2 组件依赖关系

```
README.md  ──(引用)──>  binary_search.py
                              ^
                              | 依赖
                              |
test_binary_search.py  ──(导入)──>  binary_search.py
```

- `test_binary_search.py` 从 `binary_search.py` 导入 `binary_search` 函数
- `README.md` 引用 `binary_search.py` 中的函数签名和用法
- 三者之间无循环依赖

## 3. 接口定义

### 3.1 binary_search.py 对外接口

```python
def binary_search(arr: list[int], target: int) -> int:
    """在已排序的升序列表中查找目标值。

    Args:
        arr: 已按升序排序的整数列表。
        target: 要查找的目标整数值。

    Returns:
        目标值在列表中的索引（0-based），若不存在则返回 -1。

    Raises:
        TypeError: 如果 arr 不是 list 类型。
        TypeError: 如果 target 不是 int 类型。
    """
```

### 3.2 内部辅助函数（非导出）

无。算法实现完全内联在 `binary_search` 函数中，无需额外辅助函数。

### 3.3 测试接口

```python
# test_binary_search.py
import pytest
from binary_search import binary_search
```

## 4. 数据流设计

### 4.1 正常查找数据流

```
调用方传入 arr, target
        │
        ▼
┌─────────────────────────────┐
│ 参数校验                    │
│  - arr 是 list 类型？       │
│  - target 是 int 类型？     │
│  若否 → 抛出 TypeError      │
└─────────────────────────────┘
        │ 通过
        ▼
┌─────────────────────────────┐
│ 二分查找迭代                │
│  left = 0                   │
│  right = len(arr) - 1       │
│  while left <= right:       │
│    mid = (left + right) // 2│
│    if arr[mid] == target    │
│      → return mid           │
│    elif arr[mid] < target   │
│      → left = mid + 1       │
│    else                     │
│      → right = mid - 1      │
└─────────────────────────────┘
        │ 未找到
        ▼
    return -1
```

### 4.2 空列表数据流

```
arr = [], target = 5
        │
        ▼
left = 0, right = -1
        │
        ▼
while 0 <= -1 → False → 跳过循环
        │
        ▼
return -1
```

### 4.3 错误处理数据流

```
arr = None → TypeError("arr must be a list")
arr = "abc" → TypeError("arr must be a list")
target = "abc" → TypeError("target must be an int")
```

## 5. 算法设计

### 5.1 算法选择

| 维度 | 选择 |
|------|------|
| **算法** | 经典二分查找（迭代式） |
| **时间复杂度** | O(log n) |
| **空间复杂度** | O(1) |
| **实现方式** | 迭代（while 循环），不使用递归 |

### 5.2 关键逻辑

```
left = 0
right = len(arr) - 1

while left <= right:
    mid = left + (right - left) // 2   # 防止 (left+right) 整数溢出
    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        left = mid + 1
    else:
        right = mid - 1

return -1
```

**注意**：使用 `left + (right - left) // 2` 而非 `(left + right) // 2`，虽然 Python 整数无溢出风险，但这是二分查找的行业最佳实践，保持一致性。

### 5.3 重复值处理

当列表中存在重复值时，算法返回第一个被 mid 命中的索引。由于二分查找的 mid 选择取决于 left/right 的收敛路径，可能返回任意匹配索引。这符合 spec FR-02 要求（不做稳定性要求）。

## 6. 技术选型

### 6.1 编程语言与运行时

| 项目 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.8+ | 团队指定；类型注解从 3.5 开始支持，3.8 起更成熟 |
| 包管理 | 无需（纯标准库实现） | 无外部依赖 |
| 测试框架 | pytest 7.x | Python 生态最流行的测试框架，支持参数化测试、fixture |
| 文档格式 | Markdown | 通用、易读、GitHub 友好 |

### 6.2 为什么选择 pytest 而非 unittest

| 维度 | pytest | unittest |
|------|--------|----------|
| 参数化测试 | `@pytest.mark.parametrize` 原生支持 | 需 `subTest` 或额外包装 |
| 断言 | 原生 `assert` 语句 | 需 `self.assertEqual()` 等 |
| 代码量 | 更简洁 | 更冗长 |
| 社区 | 更活跃 | 标准库 |

### 6.3 为什么选择迭代而非递归

| 维度 | 迭代 | 递归 |
|------|------|------|
| 空间复杂度 | O(1) | O(log n) 调用栈 |
| 栈溢出风险 | 无 | 大列表时可能栈溢出 |
| 可读性 | 简单直观 | 需理解递归思维 |
| 符合 spec | ✅ AC-15 明确要求迭代 | ❌ 不符合要求 |

## 7. 替代方案（未采纳）

### 7.1 使用 bisect 模块

```python
import bisect
def binary_search(arr, target):
    idx = bisect.bisect_left(arr, target)
    if idx < len(arr) and arr[idx] == target:
        return idx
    return -1
```

**未采纳理由**：spec AC-14 明确禁止使用 `bisect` 模块。

### 7.2 使用 list.index()

```python
def binary_search(arr, target):
    try:
        return arr.index(target)
    except ValueError:
        return -1
```

**未采纳理由**：spec AC-14 明确禁止使用 `list.index()`；且 `list.index()` 时间复杂度为 O(n)，不符合 O(log n) 要求。

### 7.3 递归实现

```python
def binary_search(arr, target, left=0, right=None):
    if right is None:
        right = len(arr) - 1
    if left > right:
        return -1
    mid = (left + right) // 2
    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        return binary_search(arr, target, mid + 1, right)
    else:
        return binary_search(arr, target, left, mid - 1)
```

**未采纳理由**：spec AC-15 明确要求迭代实现，不使用递归。

### 7.4 使用 NumPy 进行大规模查找

对于超大规模数据（10^7+），可考虑 `numpy.searchsorted`。但本项目为纯 Python 标准库实现，引入 NumPy 会增加依赖和部署复杂度，不必要。

## 8. 测试策略

### 8.1 测试分类与覆盖

| 测试类别 | 覆盖范围 | 用例数量 |
|----------|----------|----------|
| 示例测试 | spec 4.3 节全部 9 个示例 | 9 |
| 边界条件测试 | spec 第 3 节全部 10 个边界条件 | 10 |
| 错误处理测试 | spec 第 6 节全部 3 个错误场景 | 3 |
| 性能测试 | 长度 ≥ 10^5 的大列表 | 1 |
| **合计** | | **23** |

### 8.2 参数化测试设计

使用 `@pytest.mark.parametrize` 将示例和边界条件组织为参数化测试：

```python
@pytest.mark.parametrize("arr, target, expected", [
    ([1, 3, 5, 7, 9], 5, 2),       # 示例1
    ([1, 3, 5, 7, 9], 1, 0),       # 示例2
    ...
])
def test_binary_search(arr, target, expected):
    assert binary_search(arr, target) == expected
```

### 8.3 重复值测试

```python
@pytest.mark.parametrize("arr, target", [
    ([2, 2, 2], 2),
    ([1, 1, 2, 3], 1),
    ([1, 2, 2, 2, 3], 2),
])
def test_binary_search_duplicates(arr, target):
    result = binary_search(arr, target)
    assert arr[result] == target  # 验证返回值指向目标值
```

### 8.4 错误处理测试

```python
def test_arr_is_none():
    with pytest.raises(TypeError, match="arr must be a list"):
        binary_search(None, 5)

def test_arr_not_list():
    with pytest.raises(TypeError, match="arr must be a list"):
        binary_search("not a list", 5)

def test_target_not_int():
    with pytest.raises(TypeError, match="target must be an int"):
        binary_search([1, 2, 3], "not an int")
```

### 8.5 性能测试

```python
def test_large_list_performance():
    import time
    large_arr = list(range(10**6))
    start = time.time()
    result = binary_search(large_arr, 999999)
    elapsed = time.time() - start
    assert result == 999999
    assert elapsed < 0.1  # AC-11: < 0.1秒
```

## 9. 文件结构（最终产出）

```
output/auto-71436299/
├── spec.md                # 规格说明文档（已存在）
├── plan.md                # 本技术方案文档
├── tasks.md               # 任务清单（由 task-breaker 产出）
├── binary_search.py       # 二分查找实现
├── test_binary_search.py  # 单元测试
└── README.md              # 使用说明文档
```

## 10. 实施步骤与人天估算

| 步骤 | 任务 | 预估人天 | 前置依赖 | 负责人 |
|------|------|----------|----------|--------|
| 1 | 编写 tasks.md 任务清单 | 0.1 | plan.md | task-breaker |
| 2 | 实现 binary_search.py | 0.3 | tasks.md | implementer |
| 3 | 实现 test_binary_search.py | 0.3 | binary_search.py | implementer |
| 4 | 编写 README.md | 0.2 | binary_search.py | implementer |
| 5 | 代码审查 | 0.2 | 步骤 2-4 | code-reviewer |
| **合计** | | **1.1** | | |

## 11. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 大列表性能不达标 | 中等 | 低 | 使用迭代 O(log n) 算法，确保 10^6 列表 < 0.1s |
| 类型检查遗漏边界 | 低 | 低 | 使用 `isinstance()` 而非 `type()` 以支持子类 |
| 测试覆盖不全 | 中 | 低 | 参数化测试确保所有示例和边界条件覆盖 |
