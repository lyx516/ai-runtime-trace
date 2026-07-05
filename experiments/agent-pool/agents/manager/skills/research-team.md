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

资料调研、数据分析、输出报告。

## 适用场景
需要信息搜集和结构化产出的调研任务：技术调研、竞品分析、可行性研究。

## 班底成员
- `researcher` — 搜集资料，整理原始信息
- `analyst` — 分析数据，提炼结论
- `writer` — 撰写最终报告

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

---

## Gate 设计指南

此班底是**纯串行流水线**模式，每个 state 只有一个执行者。这是最简单的 gate 配置方式。

### 单 agent 串行流程的特点

- 每个 state 只有一个 actor，不需要交叉审查
- gate 全部用 `product` 类型（检查文件存在性）
- 不需要 `decision` gate 的 LLM 判断，减少 token 消耗
- 适合步骤明确、产出物清晰的管道式任务

### 如何增加审查环节

若需要审查，只需在 actors 中增加第二个 agent：
```yaml
- state: RESEARCH
  actors: researcher+reviewer
```
系统会自动让 reviewer 在 researcher 完成后审查。门禁检查会在审查通过后确认产物文件有效性。