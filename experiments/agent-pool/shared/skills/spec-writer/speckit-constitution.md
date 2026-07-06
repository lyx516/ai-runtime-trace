---
name: speckit-constitution
description: Create or update the project constitution from interactive or provided principle inputs, ensuring all dependent templates stay in sync.
---

# Spec Kit Constitution Skill

## When to Use

- Initial project setup or when governance principles need updates.

## Inputs

- User-provided principles or amendments.
- Existing `参考 constitution: constitution.md` and templates.

If the request is missing or ambiguous, ask focused questions before proceeding.

## Workflow

You are updating the project constitution at `参考 constitution: constitution.md`. This file is a TEMPLATE containing placeholder tokens in square brackets (e.g. `[PROJECT_NAME]`, `[PRINCIPLE_1_NAME]`). Your job is to (a) collect/derive concrete values, (b) fill the template precisely, and (c) propagate any amendments across dependent artifacts.

If `参考 constitution: constitution.md` is missing, do **not** edit upstream Spec Kit templates or a downloaded `spec-kit` source checkout as a substitute. Ask for the target project path or, when the user explicitly wants a new workspace, initialize one first with `specify init <name> --integration <agent> --ignore-agent-tools`, then operate on the new project's `参考 constitution: constitution.md`.

When the user provides compact governance preferences such as "简洁、高可复用性、易读、不做多余设计、宁缺毋滥", translate them into short, testable principles. Prefer fewer high-signal principles and concrete gates over broad aspirational wording.

Follow this execution flow:

1. Load the existing constitution template at `参考 constitution: constitution.md`.
   - Identify every placeholder token of the form `[ALL_CAPS_IDENTIFIER]`.
     **IMPORTANT**: The user might require less or more principles than the ones used in the template. If a number is specified, respect that - follow the general template. You will update the doc accordingly.

2. Collect/derive values for placeholders:
   - If user input (conversation) supplies a value, use it.
   - Otherwise infer from existing repo context (README, docs, prior constitution versions if embedded).
   - For governance dates: `RATIFICATION_DATE` is the original adoption date (if unknown ask or mark TODO), `LAST_AMENDED_DATE` is today if changes are made, otherwise keep previous.
   - `CONSTITUTION_VERSION` must increment according to semantic versioning rules:
     - MAJOR: Backward incompatible governance/principle removals or redefinitions.
     - MINOR: New principle/section added or materially expanded guidance.
     - PATCH: Clarifications, wording, typo fixes, non-semantic refinements.
   - If version bump type ambiguous, propose reasoning before finalizing.

3. Draft the updated constitution content:
   - Replace every placeholder with concrete text (no bracketed tokens left except intentionally retained template slots that the project has chosen not to define yet—explicitly justify any left).
   - Preserve heading hierarchy and comments can be removed once replaced unless they still add clarifying guidance.
   - Ensure each Principle section: succinct name line, paragraph (or bullet list) capturing non‑negotiable rules, explicit rationale if not obvious.
   - Ensure Governance section lists amendment procedure, versioning policy, and compliance review expectations.

4. Consistency propagation checklist (convert prior checklist into active validations):
   - Read `参考 template: plan-template.md` and ensure any "Constitution Check" or rules align with updated principles.
   - Read `参考 template: spec-template.md` for scope/requirements alignment—update if constitution adds/removes mandatory sections or constraints.
   - Read `参考 template: tasks-template.md` and ensure task categorization reflects new or removed principle-driven task types (e.g., observability, versioning, testing discipline).
   - Review runtime prompts/agents for outdated references and align with updated principles:
     - `.claude/commands/speckit.*.md`
     - `.codex/prompts/speckit.*.md`
     - `.gemini/commands/speckit.*.toml`
     - `.github/prompts/speckit.*.prompt.md`
     - `.github/agents/speckit.*.agent.md`
     - `skills/speckit-*/SKILL.md`
   - Read any runtime guidance docs (e.g., `README.md`, `docs/quickstart.md`, or agent-specific guidance files if present). Update references to principles changed.

5. Produce a Sync Impact Report (prepend as an HTML comment at top of the constitution file after update):
   - Version change: old → new
   - List of modified principles (old title → new title if renamed)
   - Added sections
   - Removed sections
   - Templates requiring updates (✅ updated / ⚠ pending) with file paths
   - Follow-up TODOs if any placeholders intentionally deferred.

6. Validation before final output:
   - No remaining unexplained bracket tokens.
   - Version line matches report.
   - Dates ISO format YYYY-MM-DD.
   - Principles are declarative, testable, and free of vague language ("should" → replace with MUST/SHOULD rationale where appropriate).
   - If no canonical test/lint/build command exists, run a focused ad-hoc verification script from an OS-safe temporary path with a `hermes-verify-` filename prefix. Check the changed constitution/templates for required synced text, unresolved placeholders, date/version consistency, stale wording, and trailing whitespace; then clean up the temporary script and report it explicitly as ad-hoc verification, not suite green.

7. Write the completed constitution back to `参考 constitution: constitution.md` (overwrite).

8. Output a final summary to the user with:
   - New version and bump rationale.
   - Any files flagged for manual follow-up.
   - Suggested commit message (e.g., `docs: amend constitution to vX.Y.Z (principle additions + governance update)`).

Formatting & Style Requirements:

- Use Markdown headings exactly as in the template (do not demote/promote levels).
- Wrap long rationale lines to keep readability (<100 chars ideally) but do not hard enforce with awkward breaks.
- Keep a single blank line between sections.
- Avoid trailing whitespace.

If the user supplies partial updates (e.g., only one principle revision), still perform validation and version decision steps.

If critical info missing (e.g., ratification date truly unknown), insert `TODO(<FIELD_NAME>): explanation` and include in the Sync Impact Report under deferred items.

Do not create a new template; always operate on the existing `参考 constitution: constitution.md` file.

## Outputs

- Updated `参考 constitution: constitution.md` (with Sync Impact Report comment)
- Any updated templates or runtime guidance files required to stay consistent with the constitution

## Next Steps

After updating the constitution:

- **Specify** new features with speckit-specify.
