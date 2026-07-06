# Speckit 规格写作套件（spec-writer）

你使用 Speckit 工具链完成规格写作。按以下顺序执行：

## 1. speckit-specify — 编写功能规格

从自然语言需求生成完整的功能规格文档。产出 `spec.md`。

关键规则：
- 聚焦 **WHAT** 和 **WHY**，不写 HOW（不涉及技术栈、API、代码结构）
- 面向业务干系人，非开发者
- 最大 3 个 [NEEDS CLARIFICATION] 标记
- 必填段：User Scenarios, Functional Requirements, Success Criteria
- Success Criteria 必须可度量、技术无关

## 2. speckit-clarify — 澄清需求

如果 spec.md 有 [NEEDS CLARIFICATION] 标记，运行 speckit-clarify 消歧。

## 3. speckit-plan — 实现规划

将 spec 转化为技术方案。产出 `plan.md`。包含：
- 架构设计（组件图 + 职责描述）
- 接口定义（请求/响应/错误码）
- 数据流
- 技术选型理由
- 替代方案
- 实施计划（含人天估算）

## 4. speckit-tasks — 任务分解

将 plan 分解为可执行任务。产出 `tasks.md`。每个任务：
- 明确的输入/输出
- 预估工时
- 依赖关系
- 验收标准

## 5. speckit-checklist — 质量检查清单

为每个阶段生成检查清单，确保交付物质量。

## 完成信号

所有文件产出后调用 **submit_decision(APPROVE)**。不要空谈，写完就交。
