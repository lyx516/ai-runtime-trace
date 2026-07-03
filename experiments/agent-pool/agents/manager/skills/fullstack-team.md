# 全栈班底

辩论定方案 → 实现 → 测试 → 文档的完整流程

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `designer`
- `critic`
- `decider`
- `implementer`
- `tester`
- `writer`

## Gate 类型
mixed

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
   - 执行: `implementer`
   - Pass → TEST
   - Fail → IMPLEMENT（最多 3 轮）
6. **TEST**: 测试验证
   - 执行: `tester`
   - Pass → DOC
   - 产物检查: `test-report.md` 存在且非空
   - Fail → IMPLEMENT（最多重试 2 次）
7. **DOC**: 撰写文档
   - 执行: `writer`
   - Pass → DONE
   - 产物检查: `README.md` 存在且非空
   - Fail → DOC（最多重试 2 次）
