# Spec-Writer Skill

基于 Hermes 内置 [speckit](https://hermes-agent.nousresearch.com/docs) 工具链的规格写作流程。

## 执行顺序

### 1. speckit-specify — 编写功能规格

从自然语言需求生成 `spec.md`。

**关键规则**:
- 聚焦 **WHAT** 和 **WHY**，不写 HOW
- Success Criteria 必须可度量、技术无关
- 最大 3 个 [NEEDS CLARIFICATION]

### 2. speckit-clarify — 澄清需求

如果 spec.md 有 [NEEDS CLARIFICATION]，消歧。

### 3. speckit-plan — 技术方案

将 spec 转化为 `plan.md`：
- 架构设计 + 组件职责
- 接口定义
- 数据流
- 技术选型理由

### 4. speckit-tasks — 任务分解

将 plan 分解为 `tasks.md`。每个任务：输入/输出/工时/依赖/验收标准。

### 5. speckit-checklist — 质量清单

生成检查清单验证交付物完整性。

## 完成信号

所有文件产出后调用 **submit_decision(APPROVE)**。
