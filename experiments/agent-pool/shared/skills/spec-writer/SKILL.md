# Spec-Writer Skill

基于 speckit-specify + speckit-clarify + speckit-plan + speckit-tasks + speckit-checklist 的规格写作流程。

## 执行顺序

### 1. speckit-specify — 编写功能规格

Input: 任务目标（从系统提示的"团队总目标"获取）。

流程：
1. 解析目标：识别 actors、actions、data、constraints
2. 不确定的方面：基于上下文合理推断，仅标记最多 3 个 [NEEDS CLARIFICATION]
3. 填写 User Scenarios & Testing
4. 生成 Functional Requirements（每条必须可测试）
5. 定义 Success Criteria（可度量、技术无关）

产出：`spec.md`

**Quality Validation**：写完后自检 —
- [ ] 无实现细节（语言/框架/API）
- [ ] 聚焦用户价值和业务需求
- [ ] 无不完整的 [NEEDS CLARIFICATION]
- [ ] 需求可测试且无歧义
- [ ] Success Criteria 可度量且技术无关
- [ ] 边界情况已识别

### 2. speckit-plan — 技术方案

产出 `plan.md`：
- 技术选型 + 理由
- 架构设计
- 数据模型
- 接口定义
- 实施阶段

### 3. speckit-tasks — 任务分解

产出 `tasks.md`。格式：
```
- [ ] T001 描述 + 文件路径
- [ ] T002 [P] 可并行任务 + 文件路径
- [ ] T003 [US1] 关联用户故事 + 文件路径
```
按 Phase 组织：Setup → Foundational → User Stories → Polish

### 完成信号

所有文件产出后调用 **submit_decision(APPROVE)**。
