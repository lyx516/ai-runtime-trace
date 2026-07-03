# 调研班底

资料调研、数据分析、输出报告

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `researcher`
- `analyst`
- `writer`

## Gate 类型
product

## 流程拓扑
1. **RESEARCH**: 调研资料 research.md
   - 执行: `researcher`
   - Pass → ANALYZE
   - 产物检查: `research.md` 存在且非空
   - Fail → RESEARCH（最多重试 2 次）
2. **ANALYZE**: 数据分析 analysis.md
   - 执行: `analyst`
   - Pass → REPORT
   - 产物检查: `analysis.md` 存在且非空
   - Fail → ANALYZE（最多重试 2 次）
3. **REPORT**: 撰写报告 report.md
   - 执行: `writer`
   - Pass → DONE
   - 产物检查: `report.md` 存在且非空
   - Fail → REPORT（最多重试 2 次）
