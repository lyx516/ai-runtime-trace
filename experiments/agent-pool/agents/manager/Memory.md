

-----
## 团队搭配经验
目标: 设计并开发一个向量数据库，要求检索性能极高，你能短时间内完成指定向量的相似向量召回 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 班底: 自动决策
## Evolution Update
修正团队搭配经验：原经验中5人团队（spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester）对于内存数据库这类compact任务过于冗余，实际运行时code-reviewer闲置、implementer返工4次，效率低。建议精简为 spec-writer + implementer + reviewer 三人组，减少plan/task-breaker层级，或让implementer兼任reviewer角色。保留原有文件操作辅助经验。
## Evolution Update
完整开发任务（含 spec/plan/代码/测试）必须使用 3 人以上团队。单 agent 无法产出可交付代码，历史证据：writer 单人任务产出率为 0%（Git 介绍、密码生成器、日志分析器均无一输出代码文件）。最小团队: spec-writer + implementer + reviewer。