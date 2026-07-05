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

方案推演、技术选型辩论、架构评审。

## 适用场景
需要多轮论证和反驳的纯方案讨论：技术选型、架构决策、设计评审。**不涉及文件产出**（纯 LLM 判断）。

## 班底成员
- `designer` — 提出初版方案
- `critic` — 审查方案，指出缺陷
- `mediator` — 无法达成一致时调解
- `decider` — 最终拍板

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

---

## Gate 设计指南

此班底**全部使用 `decision` gate**，没有文件检查。每个 agent 通过 `submit_decision()` 做判断。

### 纯讨论流程的设计要点

- 不需要产出物，全部用 `type: decision` 即可
- fail 目标设为自身形成 revision 循环（如 `DESIGN→fail: DESIGN`）
- 调解失败时可跳到 `ABORT` 终止讨论
- max 轮数耗尽后默认走 `on_exhausted` 或 `on_fail` 目标

### 常见变体

**双向辩论版**（designer 和 critic 交替反驳）：
```yaml
- state: PROPOSE
  actors: designer
  gate:
    type: decision
    pass: CHALLENGE
    fail: PROPOSE
    max: 3
- state: CHALLENGE
  actors: critic
  gate:
    type: decision
    pass: PROPOSE
    fail: MEDIATE
    max: 5
- state: MEDIATE
  actors: mediator
  gate:
    type: decision
    pass: DONE
    fail: ABORT
    max: 2
```

**思路：用 max 控制每轮对话长度，fail 到争议处理 state（不是直接 ABORT）让 discussion 能收敛。**