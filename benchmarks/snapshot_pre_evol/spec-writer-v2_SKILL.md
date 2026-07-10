
- skill_load 失败后先使用 search_files 查找 experiments/agent-pool/skills/ 下可用 skill 文件，确认名称存在后再重试 skill_load

- skill_load 失败时先检查技能名是否准确，若连续失败则跳过 skill_load 直接使用默认方法

- skill_load 前先检查 skill 文件是否存在，避免加载不存在的 skill 导致失败

- skill_load 前先用 search_files 确认 skill 文件名存在，避免加载不存在的 skill
