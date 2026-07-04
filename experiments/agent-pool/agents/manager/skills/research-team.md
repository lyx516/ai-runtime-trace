---
name: 调研班底
description: 资料调研、数据分析、输出报告
output_base: "output/{flow_id}"
agents:
- researcher
- analyst
- writer
flow:
- state: RESEARCH
  description: 调研资料
  actors: researcher
  gate:
    type: product
    file: research.md
    pass: ANALYZE
    fail: RESEARCH
    max: 2
  output_artifacts:
  - research.md
- state: ANALYZE
  description: 数据分析
  actors: analyst
  gate:
    type: product
    file: analysis.md
    pass: REPORT
    fail: ANALYZE
    max: 2
  output_artifacts:
  - analysis.md
- state: REPORT
  description: 撰写报告
  actors: writer
  gate:
    type: product
    file: report.md
    pass: DONE
    fail: REPORT
    max: 2
  output_artifacts:
  - report.md
---



# 调研班底

资料调研、数据分析、输出报告

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `researcher`
- `analyst`
- `writer`

## 流程拓扑
1. **RESEARCH**: 调研资料
   - 执行: `researcher`
   - Pass → ANALYZE
   - 产物检查: `research.md` 存在且非空
   - Fail → RESEARCH（最多 2 轮）
2. **ANALYZE**: 数据分析
   - 执行: `analyst`
   - Pass → REPORT
   - 产物检查: `analysis.md` 存在且非空
   - Fail → ANALYZE（最多 2 轮）
3. **REPORT**: 撰写报告
   - 执行: `writer`
   - Pass → DONE
   - 产物检查: `report.md` 存在且非空
   - Fail → REPORT（最多 2 轮）
