---
name: 全栈班底
description: 辩论→实现→测试→文档的完整流程
output_base: "output/{flow_id}"
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
  output_artifacts:
  - test-report.md
- state: DOC
  description: 撰写文档
  actors: writer
  gate:
    type: product
    file: README.md
    pass: DONE
    fail: DOC
    max: 2
  output_artifacts:
  - README.md
---

# 全栈班底

辩论→实现→测试→文档的完整流程。

## 适用场景
需要完整交付的综合性任务：从方案讨论、设计决策、编码实现、测试验证到文档输出。

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
   - 纯 decision gate，无文件
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
   - 执行: `implementer+tester`（串行：implementer 写，tester 审查）
   - gate 类型: decision（tester 读代码后判断）
   - Pass → TEST
   - Fail → IMPLEMENT（最多 3 轮）
6. **TEST**: 测试验证
   - 执行: `tester`
   - gate 类型: product（检查 test-report.md）
   - Pass → DOC
   - Fail → IMPLEMENT（最多 2 轮）
7. **DOC**: 撰写文档
   - 执行: `writer`
   - gate 类型: product（检查 README.md）
   - Pass → DONE
   - Fail → DOC（最多 2 轮）

---

## Gate 设计指南

此班底展示了**混合 gate 配置模式**——前半段辩论用 `decision`，后半段实现用 `product`。

### 混合模式的关键设计原则

- **前期决策阶段用 decision gate**：方案讨论需要 LLM 主观判断，不需要文件产出
- **后期实施阶段用 product gate**：编码、测试、文档有明确的物理产出，检查文件更可靠
- **state 间的 pass/fail 跳转**：可以跳到任意 state（不一定是相邻的），如 `CRITIQUE→pass: REVISION` 往返跳，`CRITIQUE→fail: REVISION` 始终让 designer 回应
- **跨阶段的 fail 回退**：测试失败 (`TEST→fail: IMPLEMENT`) 直接回到编码阶段，不是只回到测试本身 —— 这样编码者必须修复问题

### 常见 gate 回退模式

| 模式 | 配置 | 场景 |
|------|------|------|
| 自身 revision | `fail: 当前 STATE` | 写文档、代码 —— 自己改到通过 |
| 回退上游 | `fail: 前一 STATE` | 审查失败 → 回退到执行者重做 |
| 争议调解 | `fail: MEDIATE` | 无法达成一致 → 引入第三方 |
| 直接终止 | `fail: ABORT` | 无可挽回的失败 |