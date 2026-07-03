# 快捷修复班底

简单任务的快速实现+测试，不走辩论

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `implementer`
- `tester`

## Gate 类型
product

## 流程拓扑
1. **IMPLEMENT**: 修复/实现
   - 执行: `implementer`
   - Pass → TEST
   - Fail → IMPLEMENT（最多 2 轮）
2. **TEST**: 测试验证
   - 执行: `tester`
   - Pass → DONE
   - 产物检查: `test-report.md` 存在且非空
   - Fail → IMPLEMENT（最多重试 2 次）
