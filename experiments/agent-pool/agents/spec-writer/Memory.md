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
