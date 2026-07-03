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
目标: 设计一套 kv cache 缓存系统，从零完整实现,使用 python，新建独立文件夹，要求极致性能 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 效果: 团队缺乏文档驱动协作，spec/plan/task 均未产出，导致实现和测试迭代低效。建议强制要求每个 agent 产出文件，并设置 gate 检查。
Gate建议: 在 spec-writer、plan-maker、task-breaker 后增加 gate：必须产出对应文件且通过评审，才能进入下一阶段。implementer 和 tester 迭代时，每次提交必须附带变更文件路径。