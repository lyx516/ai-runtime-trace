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
目标: 实现一个嵌入式 KV 存储引擎，支持：1) TTL 过期 2) WAL 预写日志持久化 3) LRU 缓存 4) 读写锁 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 效果: spec→plan→task→implement→review→test 的线性流水线效果出色，各环节衔接紧密。spec-writer 和 tester 的边界条件设计尤为关键，确保了实现质量。建议在复杂项目中增加并行实现环节。
Gate建议: 建议在 implementer 和 tester 之间增加 '集成测试门禁'，要求所有模块集成后通过基本功能测试再进入详细测试阶段，可早期发现接口不兼容问题。同时，在 code-reviewer 之后增加 '性能门禁'，对关键路径（如 LRU 命中率、WAL 写入延迟）进行基准测试。