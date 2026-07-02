<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Placeholder Principle 1 -> I. Minimal Useful Scope
- Placeholder Principle 2 -> II. Reusable Core Only
- Placeholder Principle 3 -> III. Readability Is a Product Requirement
- Placeholder Principle 4 -> IV. Evidence Before Expansion
- Placeholder Principle 5 -> V. 宁缺毋滥 Quality Bar
Added sections:
- Runtime Trace Constraints
- Development Workflow
Removed sections:
- Placeholder sections and example comments
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md
- ✅ .specify/templates/tasks-template.md
Runtime guidance reviewed:
- ✅ .agents/skills/speckit-implement/SKILL.md updated
- ✅ Other .agents/skills/speckit-*.md load the constitution dynamically; no hard-coded update required
Follow-up TODOs: None
-->
# AI Runtime Trace Constitution

## Core Principles

### I. Minimal Useful Scope
Every feature MUST define the smallest independently useful outcome before design or implementation.
Optional capabilities, broad platform ambitions, and speculative extension points MUST be deferred unless
they are required by the current user story. Rationale: this project exists to turn runtime behavior into
AI-readable facts; unfocused scope makes the trace harder to trust and harder to reuse.

### II. Reusable Core Only
Shared abstractions MUST be created only when at least two concrete uses exist, or when a boundary is
unavoidable for isolation, safety, or external integration. Single-use wrappers, empty interfaces,
placeholder services, and configuration hooks without an immediate consumer are prohibited. Rationale:
reusability comes from stable semantics and repeated use, not from premature layering.

### III. Readability Is a Product Requirement
Code, specifications, schemas, and generated trace artifacts MUST be readable without private context.
Names MUST describe domain intent, data flow, and causality. Required documents MUST explain what the
system records, why it records it, and how an AI or human validates the result. Rationale: an AI-readable
runtime trace cannot be built on unreadable project artifacts.

### IV. Evidence Before Expansion
New mechanisms MUST be justified by direct evidence: a user requirement, a failing validation case, a
measured limitation, or a minimal prototype. When alternatives exist, the chosen path MUST state why
simpler options were rejected. Rationale: the project favors empirical proof over speculative design.

### V. 宁缺毋滥 Quality Bar
Incomplete or low-confidence capabilities MUST be left out rather than shipped as vague, misleading, or
unverifiable behavior. Public outputs MUST avoid fake precision, placeholder TODOs, and undocumented
best-effort semantics. Rationale: missing data is safer than incorrect execution facts that mislead AI
analysis.

## Runtime Trace Constraints

Runtime trace features MUST preserve causality: function spans, branch decisions, exceptions, state
changes, and external calls must be linkable through stable identifiers. Static code maps and dynamic
runtime events MUST use stable IDs that survive line-number drift when practical. Captured values MUST be
summarized by default; full values require an explicit need, redaction strategy, and validation path.

## Development Workflow

Work MUST proceed in thin, independently validated increments. Each specification MUST include explicit
non-goals. Each plan MUST pass the constitution check before research and after design. Each task list
MUST keep work tied to user stories and MUST exclude speculative infrastructure not required by those
stories. Validation can be a test, trace comparison, prototype run, or documented manual check, but it
MUST be concrete and repeatable.

## Governance

This constitution supersedes conflicting templates, plans, tasks, and ad-hoc implementation preferences.
Amendments require a documented rationale, a semantic version bump, and a sync review of dependent Spec
Kit templates and runtime agent guidance. Compliance is reviewed at every plan, task, and implementation
checkpoint.

Versioning policy:
- MAJOR: Removes or redefines a principle in a way that changes allowed project behavior.
- MINOR: Adds a principle, mandatory section, or materially expands governance.
- PATCH: Clarifies wording without changing project obligations.

**Version**: 1.0.0 | **Ratified**: 2026-07-01 | **Last Amended**: 2026-07-01
