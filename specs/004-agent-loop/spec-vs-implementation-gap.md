# Spec vs 实现差异分析

对比 001-spec 和 004-spec 的当前实现差距。

## 001 Spec (Hermes Flow FSM) — 23 个 FR

| FR | 标题 | 状态 | 说明 |
|----|------|------|------|
| FR-001 | Flow 定义声明 | ✅ | YAML → FlowDefinition 可运行 |
| FR-002 | Flow 预检校验 | ✅ | `validate_flow()` 已实现 8 项检查并在 `flow_init` 中调用 |
| FR-003 | 持久化 runtime 记录 | ✅ | SQLite run record + transitions + decisions |
| FR-004 | Hermes worker session 作为执行单元 | △ 折中 | 用 delegate_task 桥接，不是全量 Hermes worker profile。spec 说 "canonical"，当前是 "delegate_task subagent"——已偏差但 004-spec 已将此 deferred |
| FR-005 | 状态特定 context packet | ✅ | `build_agent_prompt()` + context.json 包含 soul、inbox、gate |
| FR-006 | 上下文隔离 | ⚠️ 部分 | inbox 有 role 过滤，但 `read_scope`/`write_scope` 未实施，agent 可以读任何文件 |
| FR-007 | 结构化消息 | ✅ | MessageEnvelope 含 sender、recipients、visibility、kind、state、artifacts |
| FR-008 | 原子 routing + zero delivery | ✅ | `validate_message` 在 routing.py |
| FR-009 | 仅 authorized recipients 收信 + sender 权限 | ✅ | routing 检查 state 的 message_acceptance 和 terminal；`flow_send` 检查 from_role 是当前 state 的 actor |
| FR-010 | 多种 gate 类型 | ⚠️ 部分 | 仅实现了 **decision** gate。required_acknowledgements、required_artifact_markers、human_approval 未实现 |
| FR-011 | 自动推进 | ✅ | RuntimeLoop._try_evaluate_gate |
| FR-012 | 失败 gate 路由 revision | ✅ | engine.evaluate_gate 返回 on_fail 后 advance_state |
| FR-013 | max_rounds 强制限轮 | ✅ | engine.evaluate_gate 在 >max_rounds 时路由 on_exhausted |
| FR-014 | 人工升级 | △ 骨架 | YAML schema 支持 HUMAN_ESCALATION 状态但**无实际 escalation 机制**（没有通知人、没有暂停 loop） |
| FR-015 | Status 视图 | ✅ | `flow_status()` + `agent_query_status()` |
| FR-016 | Audit trail | ✅ | audit_events 表记录 transitions、messages、decisions、gate evaluations |
| FR-017 | 中断后 resume | ❌ 缺失 | 无 `flow_resume` 工具，无 "从上次 state 恢复" 的入口 |
| FR-018 | 终端状态明确 | ✅ | completed / aborted / escalated 三态 |
| FR-019 | 修改 flow 定义拒绝 | ❌ 缺失 | 无 `flow_definition_changed` 检测，无 human confirmation 机制 |
| FR-020 | 主 session 作 conductor | ✅ | RuntimeLoop 就是 conductor |
| FR-021 | 持久 role profile 模板 | ❌ 缺失 | agent_bindings 存储了 profile_name 但**无 profile 模板系统**（soul、skills、toolsets 不来自模板） |
| FR-022 | 长期记忆 opt-in | ❌ 缺失 | memory_mode 字段存在但**无实际 enforce**（run_isolated/retained 不改变行为） |
| FR-023 | 项目本地 runtime 是权威源 | ✅ | SQLite 是单一真实来源 |

### 001 Spec Success Criteria

| SC | 标题 | 状态 | 说明 |
|----|------|------|------|
| SC-001 | 30s 内启动三 agent flow | ✅ | flow_init + loop.start() 在 1s 内 |
| SC-002 | 100% 无效 flow 被拒绝 | ❌ 缺失 | 无 comprehensive validate_flow() |
| SC-003 | 零部分交付 / 超范围收信 | ⚠️ 部分 | routing 检查收件人但**不检查发送者权限** |
| SC-004 | 95% 自动推进，change request 时永不推进 | ✅ | gate 严格 all-required |
| SC-005 | max_rounds 后 escalation | ✅ | engine 实现 |
| SC-006 | 1min 内查看 run 状态 | ✅ | flow_status |
| SC-007 | 中断后 resume 不重复 | ❌ 缺失 | 无 resume 入口 |
| SC-008 | 完整 audit trail | ✅ | audit_events 表 |
| SC-009 | 默认 memory 隔离 | ❌ 缺失 | memory_mode 不改变行为 |

---

## 004 Spec (Agent Loop 执行层) — 15 个 FR

| FR | 标题 | 状态 | 说明 |
|----|------|------|------|
| FR-001 | agent_inbox_read | ✅ | 实现 |
| FR-002 | agent_message_send | ✅ | 代理到 flow_send |
| FR-003 | agent_submit_decision | ✅ | 代理到 flow_decide |
| FR-004 | tracer.span 包装 | ✅ | 所有函数都有 |
| FR-005 | RuntimeLoop 后台 daemon | ✅ | tick 循环 |
| FR-006 | Tick 检测 gate + 自动推进 | ✅ | _try_evaluate_gate |
| FR-007 | Inbox 驱动 session 调度 | ✅ | _dispatch_from_inboxes + _dispatch_first_entry |
| FR-008 | Idle timeout 检测 | ✅ | _check_idle_timeout |
| FR-009 | 终端状态停止 | ✅ | COMPLETED/ABORTED 检测 |
| FR-010 | Context packet 包含完整信息 | ✅ | soul、inbox、gate、tools |
| FR-010a | delegate_task 作为 spawn 机制 | ✅ | broker_tick 自托管 + manifest + build_delegate_goal 完整链路 |
| FR-011 | Session 最大时长 | ❌ 缺失 | 无 timeout tracking |
| FR-012 | Session 一次工作周期 | ✅ | 每次 inbox 触发新 session |
| FR-013 | 多轮 inbox 驱动讨论 | △ 机制就绪 | inbox→dispatch 循环已实现，但**agent_runner 规则引擎无法做真正的 LLM 讨论** |
| FR-014 | soul 注入 context | ✅ | 已实现 |
| FR-015 | Revision loop + max_rounds | ✅ | engine 实现 |

### 004 Spec Success Criteria

| SC | 状态 | 说明 |
|----|------|------|
| SC-001 | agent_tools 可调用 + 结果持久化 | ✅ |
| SC-002 | 5s 内自动推进 | ✅ |
| SC-003 | 多轮讨论端到端 (3 runs) | △ 机制就绪但**未验证**——需要 delegate_task LLM 子 agent 实际运行 |
| SC-004 | max_rounds=3 后 escalation | ✅ engine 实现 |
| SC-005 | 每次 session 有 trace | ✅ |

---

## 差距分类 & 建议优先级

### P0 — 必须补（阻止基本可用） ✅ 已全部完成

| 差距 | Spec | 状态 |
|------|------|------|
| Flow 预检校验 + sender 权限 | 001 FR-002, FR-009 | ✅ |
| delegate_task 自动化 (broker) | 004 FR-010a | ✅ |
| agent_runner 决策改进 | 004 SC-003 | ✅ |

### P1 — 建议补

| 差距 | Spec | 工作量 |
|------|------|--------|
| flow_resume (已在 tools.py 中) | 001 FR-017 | ✅ 已有 |
| human escalation 实际动作 | 001 FR-014 | ✅ 已实现 |

### P2 — 锦上添花

| 差距 | Spec | 工作量 |
|------|------|--------|
| Other gate types (acknowledgement, artifact, human) | 001 FR-010 | 高 |
| read_scope / write_scope context 隔离 | 001 FR-006 | 中 |
| Profile 模板系统 | 001 FR-021 | 中 |
| memory_mode 实际 enforce | 001 FR-022 | 低 |
| Session timeout (004 FR-011) | 004 FR-011 | 低 |
| Flow 定义变更检测 | 001 FR-019 | 低 |

---

## 结论

**核心差距只有两个 P0**：

1. **delegate_task 自动化** — 需要创建 Hermes cron job 或 tool 来定期扫描 manifest → 调用 delegate_task
2. **LLM 决策** — delegate_task 子 agent 拿到 goal 后会用 LLM 思考，但需要确保 goal 内容足够触发真实讨论（当前 `build_delegate_goal` 已准备）

这两个补齐后，004-spec 的 SC-003（多轮讨论端到端）就能通过，项目就从"演示"变成"可用"。
