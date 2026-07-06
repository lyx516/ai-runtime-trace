
# SKILL: 文件写入操作

## 写入前验证
- 确认目标文件路径：如果路径不含 `.md` 后缀，且内容为 Markdown 格式，必须补全为 `.md`。
- 检查目标文件是否存在：若存在且需要追加，先使用 `file_read` 读取现有内容；若无需覆盖，则使用追加模式或正确处理。
- 避免空内容：确保写入内容非空，且格式正确（例如 Markdown 标题、列表等语法）。

## 示例

**场景**：需要将评审结果写入 `critique_output.md`
```
✅ 正确做法：
- 调用 `file_write` 时，路径设为 "critique_output.md"
- 内容包含完整 Markdown 正文，如 `# Critique Results\n\n...`

❌ 常见错误：
- 路径缺少 `.md` 后缀
- 内容为纯文本无 Markdown 结构
- 未确认文件是否存在直接覆盖，导致丢失其他 agent 的已有内容
```

## 故障回退
- 若 `file_write` 失败，先检查路径和内容格式，重新修正后重试，最多重试 2 次。
- 若仍失败，改用 `agent_message_send` 通知 gate 或相关 agent 手动处理。
