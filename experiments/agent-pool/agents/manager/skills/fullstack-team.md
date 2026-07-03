---
name: 全栈班底
description: 辩论→实现→测试→文档的完整流程
agents:
- designer
- critic
- decider
- implementer
- tester
- writer
flow:
- state: DESIGN
  description: 设计方案
  actors: designer
  gate:
    type: decision
    pass: CRITIQUE
    fail: DESIGN
    max: 2
- state: CRITIQUE
  description: 评审方案
  actors: critic
  gate:
    type: decision
    pass: REVISION
    fail: REVISION
    max: 3
- state: REVISION
  description: 修订方案
  actors: designer
  gate:
    type: decision
    pass: CRITIQUE
    fail: FINAL_DECISION
    max: 3
- state: FINAL_DECISION
  description: 决策拍板
  actors: decider
  gate:
    type: decision
    pass: IMPLEMENT
    fail: ABORT
    max: 2
- state: IMPLEMENT
  description: 实现代码
  actors: implementer+tester
  gate:
    type: decision
    pass: TEST
    fail: IMPLEMENT
    max: 3
- state: TEST
  description: 测试验证
  actors: tester
  gate:
    type: product
    file: test-report.md
    pass: DOC
    fail: IMPLEMENT
    max: 2
- state: DOC
  description: 撰写文档
  actors: writer
  gate:
    type: product
    file: README.md
    pass: DONE
    fail: DOC
    max: 2
---

# 全栈班底

辩论→实现→测试→文档的完整流程

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `designer`
- `critic`
- `decider`
- `implementer`
- `tester`
- `writer`

## 流程拓扑
1. **DESIGN**: 设计方案
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → DESIGN（最多 2 轮）
2. **CRITIQUE**: 评审方案
   - 执行: `critic`
   - Pass → REVISION
   - Fail → REVISION（最多 3 轮）
3. **REVISION**: 修订方案
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → FINAL_DECISION（最多 3 轮）
4. **FINAL_DECISION**: 决策拍板
   - 执行: `decider`
   - Pass → IMPLEMENT
   - Fail → ABORT（最多 2 轮）
5. **IMPLEMENT**: 实现代码
   - 执行: `implementer+tester`
   - Pass → TEST
   - Fail → IMPLEMENT（最多 3 轮）
6. **TEST**: 测试验证
   - 执行: `tester`
   - Pass → DOC
   - 产物检查: `test-report.md` 存在且非空
   - Fail → IMPLEMENT（最多 2 轮）
7. **DOC**: 撰写文档
   - 执行: `writer`
   - Pass → DONE
   - 产物检查: `README.md` 存在且非空
   - Fail → DOC（最多 2 轮）
