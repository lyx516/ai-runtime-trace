# 辩论班底

方案推演、技术选型辩论、架构评审

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `designer`
- `critic`
- `mediator`
- `decider`

## Gate 类型
decision

## 流程拓扑
1. **DESIGN**: 设计者出方案
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → DESIGN（最多 3 轮）
2. **CRITIQUE**: 评论者挑战方案
   - 执行: `critic`
   - Pass → REVISION
   - Fail → REVISION（最多 3 轮）
3. **REVISION**: 设计者回应批评
   - 执行: `designer`
   - Pass → CRITIQUE
   - Fail → MEDIATE（最多 3 轮）
4. **MEDIATE**: 调解者化解分歧
   - 执行: `mediator`
   - Pass → FINAL_DECISION
   - Fail → ABORT（最多 2 轮）
5. **FINAL_DECISION**: 决策者拍板
   - 执行: `decider`
   - Pass → DONE
   - Fail → ABORT（最多 2 轮）
