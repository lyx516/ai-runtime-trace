---
name: 辩论班底
description: 方案推演、技术选型辩论、架构评审
output_base: "output/{flow_id}"
agents:
- designer
- critic
- mediator
- decider
flow:
- state: DESIGN
  description: 设计方案
  actors: designer
  gate:
    type: decision
    pass: CRITIQUE
    fail: DESIGN
    max: 3
- state: CRITIQUE
  description: 审查方案
  actors: critic
  gate:
    type: decision
    pass: REVISION
    fail: REVISION
    max: 3
- state: REVISION
  description: 回应批评
  actors: designer
  gate:
    type: decision
    pass: CRITIQUE
    fail: MEDIATE
    max: 3
- state: MEDIATE
  description: 调解分歧
  actors: mediator
  gate:
    type: decision
    pass: FINAL_DECISION
    fail: ABORT
    max: 2
- state: FINAL_DECISION
  description: 决策拍板
  actors: decider
  gate:
    type: decision
    pass: DONE
    fail: ABORT
    max: 2
---

# 辩论班底

方案推演、技术选型辩论、架构评审

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `designer`
- `critic`
- `mediator`
- `decider`

## 流程拓扑
1. **DESIGN**: 设计方案
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → DESIGN（最多 3 轮）
2. **CRITIQUE**: 审查方案
   - 执行: `critic`
   - Pass → REVISION
   - Fail → REVISION（最多 3 轮）
3. **REVISION**: 回应批评
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → MEDIATE（最多 3 轮）
4. **MEDIATE**: 调解分歧
   - 执行: `mediator`
   - Pass → FINAL_DECISION
   - Fail → ABORT（最多 2 轮）
5. **FINAL_DECISION**: 决策拍板
   - 执行: `decider`
   - Pass → DONE
   - Fail → ABORT（最多 2 轮）
