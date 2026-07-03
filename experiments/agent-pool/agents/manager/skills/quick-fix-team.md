---
name: 快捷修复班底
description: 简单任务的快速实现+测试，不走辩论
agents:
- implementer
- tester
flow:
- state: IMPLEMENT
  description: 修复/实现
  actors: implementer
  gate:
    type: decision
    pass: TEST
    fail: IMPLEMENT
    max: 2
- state: TEST
  description: 测试验证
  actors: tester
  gate:
    type: product
    file: test-report.md
    pass: DONE
    fail: IMPLEMENT
    max: 2
---

# 快捷修复班底

简单任务的快速实现+测试，不走辩论

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `implementer`
- `tester`

## 流程拓扑
1. **IMPLEMENT**: 修复/实现
   - 执行: `implementer`
   - Pass → TEST
   - Fail → IMPLEMENT（最多 2 轮）
2. **TEST**: 测试验证
   - 执行: `tester`
   - Pass → DONE
   - 产物检查: `test-report.md` 存在且非空
   - Fail → IMPLEMENT（最多 2 轮）
