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
目标: 设计一套 kv cache 缓存系统，从零完整实现,使用 python，新建独立文件夹，要求极致性能 | 团队: designer, critic, decider, implementer, tester, writer | 效果: 当前 team 搭配（designer-critic-decider-implementer-tester-writer）因 designer 不产出设计、decider 不介入决策而完全失效。critic 孤掌难鸣，流程在评审阶段死锁。
Gate建议: 建议在 [DESIGN] 阶段后增加 '设计交付物检查 gate'：若 designer 在指定轮次内未产出符合 critic 要求的设计文档，则自动触发 decider 介入，decider 需在 1 轮内做出裁决（强制要求 designer 产出或更换 designer）。同时增加 'decider 活跃度 gate'：若 decider 连续 2 轮无有效决策，则自动升级到 manager 处理。