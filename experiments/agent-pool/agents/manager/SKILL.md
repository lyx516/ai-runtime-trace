

## Evolution Update
在 manager 的 SKILL.md 的选队规则中追加一条：**文件操作环境预检** —— 当任务包含文件创建、写入或修改时，必须确保所选 writer agent 具备环境预检能力（如确保工作目录存在、提供模板文件），或搭配一个具备预检能力的 agent（例如 quick-fix-team 中的预检 agent）。若无法满足，则应在 flow 设计时显式添加一个初始化步骤（例如使用 skill 或 tool 预创建目录）。此规则来源于历史教训：简单任务中仅选一个 writer 导致工具失败 2 次，原因是缺少环境准备和 skill 引导。

