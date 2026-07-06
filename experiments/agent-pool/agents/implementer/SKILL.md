
## Evolution Update
在 SKILL.md 末尾追加以下内容（基于 tool_failures 证据：file_read×3, code_exec×1, search_files×1）：

## 错误处理与预防

- **文件读取预检**：在调用 `file_read` 前，使用 `pathlib.Path.exists()` 确认文件存在；相对路径应通过 `Path(__file__).parent / 'relative/path'` 解析为绝对路径，避免因路径错误导致失败。
- **代码执行重试**：`code_exec` 执行后捕获异常，若失败则自动重试一次，并记录错误信息供后续排查。
- **搜索优化**：`search_files` 优先使用精确的 glob 模式（如 `**/*.py`），并限制搜索范围为项目根目录，减少无结果搜索。

