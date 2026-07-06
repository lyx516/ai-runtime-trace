# Implementer 技能

## 可用工具

- `write_file`: 写入文件到工作目录
- `file_read`: 读取文件内容
- `terminal`: 执行终端命令
- `search_files`: 搜索文件或内容
- `patch`: 编辑现有文件
- `code_exec`: 执行代码片段

## 关键规则

- 在 `write_file` 前确认目录存在，必要时用 `terminal mkdir -p`
- `code_exec` 失败时自动重试一次，记录错误信息
- `search_files` 优先使用精确 glob 模式，限制搜索范围

- search_files 连续失败时，改用 terminal 执行 find/grep 作为 fallback 查找文件
