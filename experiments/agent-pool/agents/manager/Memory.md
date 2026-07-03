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
目标: 实现一个嵌入式 KV 存储引擎，支持：1) TTL 过期 2) WAL 预写日志持久化 3) LRU 缓存 4) 读写锁 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 效果: 本次仅使用了 spec-writer 一个 agent，适合快速产出规格，但缺乏后续实现和验证环节，团队搭配不完整。建议在复杂任务中启用全流程班底。
Gate建议: 建议在 spec-writer 完成后增加一个 gate，检查规格是否包含接口签名、数据结构定义和边界条件，确保可实施性后再进入下一阶段。