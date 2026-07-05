---
name: 快捷修复班底
description: 简单任务的快速实现+测试，不走辩论
output_base: "output/{flow_id}"
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
  output_artifacts:
  - test-report.md
---

# 快捷修复班底

简单任务的快速实现+测试，不走辩论。

## 适用场景
已知方案的简单修复或增量实现：bug 修复、小功能添加、已知问题的快速修改。**不需要方案讨论，直接编码+测试。**

## 班底成员
- `implementer` — 实现代码
- `tester` — 测试验证

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

---

## Gate 设计指南

此班底是最小 2-agent 配置，适合快速迭代场景。

### 最小 2-agent 模式的特点

- 执行者先产出，审查者后检验 —— 不共享 state
- fail 始终回到 IMPLEMENT（执行者修，不是测试者修）
- 执行用 `decision` gate（主观判断），测试用 `product` gate（文件检查）
- 适合外部复杂、内部标准化的场景

### 如何从中扩展

如果修复变复杂，可以：
- 在 IMPLEMENT 前加一个 PLAN 状态（变成 mini spec-team）
- 在 TEST 后加一个 REVIEW 状态（增加最终审查环节）
- 在 IMPLEMENT 中把 tester 加到 actors 实现交叉审查（`actors: implementer+tester`）

所有扩展只需在 flow 数组中追加或插入新 state 节点即可。