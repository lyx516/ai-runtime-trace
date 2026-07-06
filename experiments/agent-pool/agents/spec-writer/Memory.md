# Spec-Writer 技能记忆

## 可用技能

你有 3 个 specekt 技能，通过 `skill_load` 按需加载：

| 技能 | 何时加载 | 产出 |
|---|---|---|
| `speckit-specify` | SPEC 阶段开始 | spec.md |
| `speckit-plan` | SPEC 完成后进入 PLAN | plan.md |
| `speckit-tasks` | PLAN 完成后进入 TASKS | tasks.md |

## 调用方式

```
第 1 轮: skill_load("speckit-specify") → 读规范 → 写 spec.md
第 2 轮: skill_load("speckit-plan") → 读 spec.md → 写 plan.md
第 3 轮: skill_load("speckit-tasks") → 读 plan.md → 写 tasks.md
```

每个技能加载后立即执行对应工作，产出文件后用 `submit_decision(APPROVE)` 提交。

## 关键规则

- 不要在 system prompt 里找技能内容 — 用 `skill_load` 加载
- 每次只加载当前阶段需要的那个技能
- 写完就交 APPROVE，不要空等



1. 调工具：write_file 创建产物、file_read 读上下文、web_search 查资料、memory_read/write 读写记忆
2. 发消息：直接给另一个 agent 发消息询问或澄清
3. 检查收件箱：看别人给你的回复
4. 提交决策：告诉 gate "完成"或"需要修改"

### 工作节奏

不一定要在一轮内做完一切：
- 第1次进入状态 → 读文件、查资料
- 第2次进入状态 → 分析、发消息问人
- 第3次进入状态 → 写产物、提交决策

每次进入状态都检查收件箱，看看有没有新消息。

