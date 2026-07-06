# 二分查找函数 — 任务清单 (Tasks)

## 任务总览

| 任务 ID | 文件 | 前置依赖 | 预估工时 | 并行标记 |
|---------|------|----------|----------|----------|
| T001 | `binary_search.py` | 无 | 20 min | — |
| T002 | `test_binary_search.py` | T001 | 25 min | — |
| T003 | `README.md` | T001 | 15 min | [P] 可与 T002 并行 |
| T004 | 代码审查与修复 | T002, T003 | 10 min | — |

## 关键路径

```
T001 (binary_search.py) ──→ T002 (test_binary_search.py) ──→ T004 (审查)
                        └──→ T003 (README.md) [并行]
```

**关键路径总工时**: 20 + max(25, 15) + 10 = **55 min**

**并行机会**: T002 与 T003 可并行执行，依赖 T001 完成后同时启动。

---

## T001 — 实现二分查找函数

| 字段 | 内容 |
|------|------|
| **文件** | `binary_search.py` |
| **前置依赖** | 无 |
| **预期产出** | 包含 `binary_search` 函数的 Python 源文件 |
| **预估工时** | 20 min |
| **验收标准** | |

### 验收标准

1. **函数签名正确**：`def binary_search(arr: list[int], target: int) -> int:`
2. **类型校验**：
   - 若 `arr` 不是 `list` 类型（含 `None`），抛出 `TypeError("arr must be a list")`
   - 若 `target` 不是 `int` 类型，抛出 `TypeError("target must be an int")`
3. **算法正确**：
   - 使用迭代式二分查找（while 循环）
   - 使用 `left + (right - left) // 2` 计算中间索引
   - 时间复杂度 O(log n)，空间复杂度 O(1)
4. **文档完整**：包含完整的 docstring（Args、Returns、Raises 三部分）
5. **禁止使用**：`bisect` 模块、`list.index()` 方法、递归
6. **空列表处理**：`[]` 返回 `-1`
7. **代码可导入**：`from binary_search import binary_search` 无错误

### 实现要点（参考 plan.md §5）

```python
def binary_search(arr: list[int], target: int) -> int:
    """..."""
    if not isinstance(arr, list):
        raise TypeError("arr must be a list")
    if not isinstance(target, int):
        raise TypeError("target must be an int")

    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return -1
```

---

## T002 — 编写单元测试

| 字段 | 内容 |
|------|------|
| **文件** | `test_binary_search.py` |
| **前置依赖** | T001（`binary_search.py` 必须已实现） |
| **预期产出** | 使用 pytest 的完整单元测试文件 |
| **预估工时** | 25 min |
| **验收标准** | |

### 验收标准

1. **导入正确**：`from binary_search import binary_search`
2. **示例测试**（spec §4.3 — 9 个用例）：
   - `([1, 3, 5, 7, 9], 5) → 2`
   - `([1, 3, 5, 7, 9], 1) → 0`
   - `([1, 3, 5, 7, 9], 9) → 4`
   - `([1, 3, 5, 7, 9], 4) → -1`
   - `([], 1) → -1`
   - `([2, 2, 2], 2) → 0 或 1 或 2`
   - `([-5, -3, 0, 2], -3) → 1`
   - `([10], 10) → 0`
   - `([10], 5) → -1`
3. **边界条件测试**（spec §3 — 10 个条件）：
   - BC-01: 空列表 `[]` → `-1`
   - BC-02: 单元素匹配 → `0`
   - BC-03: 单元素不匹配 → `-1`
   - BC-04: 目标在开头 → `0`
   - BC-05: 目标在末尾 → `len-1`
   - BC-06: 目标小于所有元素 → `-1`
   - BC-07: 目标大于所有元素 → `-1`
   - BC-08: 重复值存在 → 返回索引指向目标值
   - BC-09: 负数查找 → 返回正确索引
   - BC-10: 最小有效长度（1 元素）→ 正常查找
4. **错误处理测试**（spec §6 — 3 个场景）：
   - `arr=None` → `TypeError("arr must be a list")`
   - `arr="not a list"` → `TypeError("arr must be a list")`
   - `target="not an int"` → `TypeError("target must be an int")`
5. **性能测试**：
   - 长度 10^6 的大列表，查找末尾元素，完成时间 < 0.1 秒
6. **测试组织**：
   - 示例和边界条件使用 `@pytest.mark.parametrize` 参数化
   - 重复值测试单独组织，验证 `arr[result] == target`
   - 错误处理使用 `pytest.raises`
   - 性能测试使用 `time.time()` 计时
7. **运行通过**：`python -m pytest test_binary_search.py -v` 全部通过

### 测试用例数量

| 类别 | 用例数 |
|------|--------|
| 示例测试（参数化） | 9 |
| 边界条件（参数化） | 10 |
| 重复值测试 | 3 |
| 错误处理 | 3 |
| 性能测试 | 1 |
| **合计** | **26** |

---

## T003 — 编写 README 文档

| 字段 | 内容 |
|------|------|
| **文件** | `README.md` |
| **前置依赖** | T001（需引用函数签名） |
| **预期产出** | 项目的使用说明文档 |
| **预估工时** | 15 min |
| **并行标记** | [P] 可与 T002 并行执行 |
| **验收标准** | |

### 验收标准

1. **标题与简介**：项目名称、一句话描述
2. **函数签名与说明**：包含完整的类型注解和参数说明
3. **用法示例**：至少 3 个代码示例（正常查找、未找到、空列表）
4. **安装与运行**：
   - 环境要求：Python 3.8+
   - 安装依赖：`pip install pytest`
   - 运行测试：`python -m pytest test_binary_search.py -v`
5. **算法说明**：简要介绍二分查找算法（O(log n) 时间复杂度）
6. **文件结构**：列出项目文件及说明
7. **格式规范**：有效的 Markdown，代码块使用正确语言标识

---

## T004 — 代码审查与修复

| 字段 | 内容 |
|------|------|
| **文件** | `binary_search.py`, `test_binary_search.py`, `README.md` |
| **前置依赖** | T002, T003 |
| **预期产出** | 审查报告 `review.md`，必要时修复代码 |
| **预估工时** | 10 min |
| **验收标准** | |

### 验收标准

1. **一致性检查**：实现与 spec 所有需求一致
2. **边界检查**：所有边界条件正确处理
3. **安全隐患**：无类型安全漏洞（如未校验类型直接使用）
4. **代码风格**：符合 PEP 8，类型注解完整
5. **测试覆盖**：所有 spec 中的验收标准都有对应测试
6. **运行验证**：`python -m pytest test_binary_search.py -v` 全部通过
7. **产出审查报告**：`review.md` 记录审查结果

---

## 依赖关系图

```
                    ┌──────────────────┐
                    │   T001           │
                    │  binary_search.py│
                    │  (无前置依赖)     │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              │              ▼
   ┌──────────────────┐      │   ┌──────────────────┐
   │   T002           │      │   │   T003           │
   │  test_binary_    │      │   │  README.md       │
   │  search.py       │      │   │  [并行]           │
   │  (依赖 T001)     │      │   │  (依赖 T001)      │
   └────────┬─────────┘      │   └────────┬─────────┘
            │                │            │
            └────────────────┼────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   T004           │
                    │  代码审查与修复   │
                    │  (依赖 T002,T003)│
                    └──────────────────┘
```

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 类型校验遗漏 `bool` 类型 | `bool` 是 `int` 的子类，`isinstance(True, int)` 为 `True` | 在 spec 层面已接受此行为；若需严格区分可在审查时讨论 |
| 性能测试在 CI 环境可能超时 | 测试不稳定 | 设置宽松阈值（< 0.2 秒），或使用 `@pytest.mark.slow` 标记 |
| pytest 未安装 | 测试无法运行 | README 中明确安装步骤 `pip install pytest` |
