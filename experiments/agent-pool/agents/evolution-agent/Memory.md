## detail 格式规则

detail 会被直接追加到目标的 Memory.md 或 SKILL.md。**禁止写元指令、证据、操作说明。** 只写可直接作为文件内容的具体改进点。

✅ 正确:
- 不做 A。遇到 B 情况时先 C 再 D。
- file_write 前必须 terminal mkdir 创建目录。
- 单 agent 不用于输出代码文件的开发任务。开发任务至少 3 人。

❌ 错误:
- "在 Memory 末尾追加一条 Evolution Update"（元指令）
- "根据 evidence: tool_failures..."（不要证据）
- "建议在 SKILL.md 中增加文件操作示例"（"建议"是元语言）
- 不可写 run_id、"追加"、"更新"、"修改" 等操作词

## 超限处理

Memory 上限 4KB，Skill 上限 8KB。超限时系统会回报错误信息和当前文件内容。你需要精简或替换最旧的条目，重新生成 detail。
