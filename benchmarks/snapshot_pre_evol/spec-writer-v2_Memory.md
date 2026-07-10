
- **必须调工具**：不能只说"我将写文件"而不调工具。说做什么就必须立刻调对应的工具。
- **不能写 stub**：写完不能只留个框架就 APPROVE，必须产出完整可读的内容。
- **优先调工具，其次发消息，最后才提交决策**：在提交 APPROVE/REQUEST_CHANGES 之前，先用 patch/file_read/web_search 等工具完成实际工作。

- skill_load 前先确认 skill 名称在 shared/skills/ 中存在，避免加载不存在的 skill 文件

- skill_load 前先 search_files 确认 skill 文件名是否存在，避免加载不存在的 skill 导致工具调用失败

- skill_load 前先用 search_files 确认 skill 文件存在，避免因名称拼写错误导致加载失败
