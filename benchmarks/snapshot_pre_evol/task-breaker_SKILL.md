
# SKILL: task-breaker 细化规则

## 任务分解粒度要求
- 每个功能模块（如SQL的SELECT、INSERT等）必须拆分为至少4个子任务：
  - 词法分析（tokenize）
  - 语法解析（parse）
  - 执行（execute）
  - 内存管理（memory allocation / cleanup）
- 若涉及索引、事务等，进一步拆分
- 子任务工时预估不超过4小时，否则继续拆分
