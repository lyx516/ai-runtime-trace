# Memory: manager
> Max length: 3000 chars. Write runtime experience here.

## 班底技能索引

skills/ 目录下的每个 .md 文件对应一个班底配置，包含：
- 推荐 agent 成员
- 流程拓扑（状态顺序 + gate 设置）
- Tree of Thought 允许多条分支

| 文件 | 班底 | 适用 |
|------|------|------|
| debate-team.md | 辩论班底 | 方案推演、技术选型辩论 |
| spec-team.md | 规格流水线 | 完整开发流程（spec→代码）|
| research-team.md | 调研班底 | 资料调研、分析报告 |
| fullstack-team.md | 全栈班底 | 辩论→实现→测试→文档 |
| quick-fix-team.md | 快捷修复 | 简单任务快速实现 |

## 使用方式

分析任务 → 选班底（可混编） → 注入对应 skill 到 agent 灵魂 → 生成 flow → 启动



-----
## 团队搭配经验
目标: 实现一个完整的向量数据库，支持亿级向量近似搜索。需要实现 HNSW 索引、IVF 索引、混合查询 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 效果: spec-plan-task-implement-review-test 的线性流水线模式在此次任务中效果良好，各环节衔接顺畅，但缺少性能基准验证环节。
Gate建议: 建议在IMPLEMENT和REVIEW之间增加一个PERFORMANCE_GATE，要求实现必须通过预设的QPS和召回率基准测试才能进入代码审查阶段。