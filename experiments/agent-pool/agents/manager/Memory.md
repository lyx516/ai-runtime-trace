

-----
## 团队搭配经验
目标: 设计并开发一个向量数据库，要求检索性能极高，你能短时间内完成指定向量的相似向量召回 | 团队: spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester | 班底: 自动决策

## Evolution Update
追加一条团队搭配经验：对于涉及文件操作的 agent（如 writer），在选队时应预加入初始化步骤（如确保工作目录存在、提供模板文件）或搭配具备环境预检能力的 agent，以减少工具失败。实践案例：简单任务中仅选一个 writer，其工具失败2次，表明缺少必要的 skill 引导或环境准备。



## Evolution Update
修正团队搭配经验：原经验中5人团队（spec-writer, plan-maker, task-breaker, implementer, code-reviewer, tester）对于内存数据库这类compact任务过于冗余，实际运行时code-reviewer闲置、implementer返工4次，效率低。建议精简为 spec-writer + implementer + reviewer 三人组，减少plan/task-breaker层级，或让implementer兼任reviewer角色。保留原有文件操作辅助经验。


## Evolution Update
根据任务复杂度动态选择 spec-team 角色：简单任务仅使用 designer+critic，避免引入 mediator 和 decider 造成闲置。仅在出现争议或需要第三方裁决时，再引入 mediator 和 decider。同时，应优先确保核心角色的工具可靠（如 designer 的文件读写能力），而非盲目增加角色数量以弥补技能不足。（evidence: spec-team 选队理由仅描述角色清单，未分析实际需求；决策序列全部为 APPROVE，无争议，无需第三方角色；且 file_write 失败表明工具技能不足，应优先确保核心角色工具可靠）

## Evolution Update
完整开发任务（含 spec/plan/代码/测试）必须使用 3 人以上团队。单 agent 无法产出可交付代码，历史证据：writer 单人任务产出率为 0%（Git 介绍、密码生成器、日志分析器均无一输出代码文件）。最小团队: spec-writer + implementer + reviewer。
