---
name: speckit-clarify
description: Identify underspecified areas in the current feature spec by asking up to 5 highly targeted clarification questions and encoding answers back into the spec.
---

# Spec Kit Clarify Skill

## When to Use

- The feature spec exists but needs targeted clarification before planning.

## Inputs

- The current feature spec in `specs/<feature>/spec.md`.
- The user's clarification intent or constraints from the request.

If the request is empty or the spec is missing, ask a targeted question before proceeding.

## Workflow

Goal: Detect and reduce ambiguity or missing decision points in the active feature specification and record the clarifications directly in the spec file.

Note: This clarification workflow is expected to run (and be completed) BEFORE the speckit-plan skill. If the user explicitly states they are skipping clarification (e.g., exploratory spike), you may proceed, but must warn that downstream rework risk increases.

Execution steps:

0. **Read the source code of ALL involved systems BEFORE asking any questions.**
   When the spec ports patterns from one system into another, read the relevant
   source files from BOTH sides. Questions answered by the code waste the quota.
   If you realize mid-clarify that you haven't read enough, proactively reset:
   discard asked questions, read the code, restart.

1. Run `.specify/scripts/bash/check-prerequisites.sh --json --paths-only` from repo root **once** (combined `--json --paths-only` mode / `-Json -PathsOnly`). Parse minimal JSON payload fields:
   - `FEATURE_DIR`
   - `FEATURE_SPEC`
   - (Optionally capture `IMPL_PLAN`, `TASKS` for future chained flows.)
   - If JSON parsing fails, abort and instruct the user to re-run speckit-specify or verify the feature branch environment.
   - For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. Load the current spec file. Perform a structured ambiguity & coverage scan using this taxonomy. For each category, mark status: Clear / Partial / Missing. Produce an internal coverage map used for prioritization (do not output raw map unless no questions will be asked).

   Functional Scope & Behavior:
   - Core user goals & success criteria
   - Explicit out-of-scope declarations
   - User roles / personas differentiation

   Domain & Data Model:
   - Entities, attributes, relationships
   - Identity & uniqueness rules
   - Lifecycle/state transitions
   - Data volume / scale assumptions

   Interaction & UX Flow:
   - Critical user journeys / sequences
   - Error/empty/loading states
   - Accessibility or localization notes

   Non-Functional Quality Attributes:
   - Performance (latency, throughput targets)
   - Scalability (horizontal/vertical, limits)
   - Reliability & availability (uptime, recovery expectations)
   - Observability (logging, metrics, tracing signals)
   - Security & privacy (authN/Z, data protection, threat assumptions)
   - Compliance / regulatory constraints (if any)

   Integration & External Dependencies:
   - External services/APIs and failure modes
   - Data import/export formats
   - Protocol/versioning assumptions

   Edge Cases & Failure Handling:
   - Negative scenarios
   - Rate limiting / throttling
   - Conflict resolution (e.g., concurrent edits)

   Constraints & Tradeoffs:
   - Technical constraints (language, storage, hosting)
   - Explicit tradeoffs or rejected alternatives

   Terminology & Consistency:
   - Canonical glossary terms
   - Avoided synonyms / deprecated terms

   Completion Signals:
   - Acceptance criteria testability
   - Measurable Definition of Done style indicators

   Misc / Placeholders:
   - TODO markers / unresolved decisions
   - Ambiguous adjectives ("robust", "intuitive") lacking quantification

   For each category with Partial or Missing status, add a candidate question opportunity unless:
   - Clarification would not materially change implementation or validation strategy
   - Information is better deferred to planning phase (note internally)

3. Generate (internally) a prioritized queue of candidate clarification questions (maximum 5). Do NOT output them all at once. Apply these constraints:
   - Maximum of 10 total questions across the whole session.
   - Each question must be answerable with EITHER:
     - A short multiple‑choice selection (2–5 distinct, mutually exclusive options), OR
     - A one-word / short‑phrase answer (explicitly constrain: "Answer in <=5 words").
   - Only include questions whose answers materially impact architecture, data modeling, task decomposition, test design, UX behavior, operational readiness, or compliance validation.
   - Ensure category coverage balance: attempt to cover the highest impact unresolved categories first; avoid asking two low-impact questions when a single high-impact area (e.g., security posture) is unresolved.
   - Exclude questions already answered, trivial stylistic preferences, or plan-level execution details (unless blocking correctness).
   - Favor clarifications that reduce downstream rework risk or prevent misaligned acceptance tests.
   - If more than 5 categories remain unresolved, select the top 5 by (Impact \* Uncertainty) heuristic.

4. Sequential questioning loop (interactive):
      - Present EXACTLY ONE question at a time.
      - Ask in the user's working language. If the user is writing Chinese, render the recommendation, question, table labels, and reply instructions in Chinese; keep option letters stable.
      - For multiple‑choice questions:
        - **Analyze all options** and determine the **most suitable option** based on:
          - Best practices for the project type
          - Common patterns in similar implementations
          - Risk reduction (security, performance, maintainability)
          - Alignment with any explicit project goals or constraints visible in the spec
        - Present your **recommended option prominently** at the top with clear reasoning (1-2 sentences explaining why this is the best choice).
     - Format as: `**Recommended:** Option [X] - <reasoning>`
     - Then render all options as a Markdown table:

     | Option | Description                                                                                         |
     | ------ | --------------------------------------------------------------------------------------------------- |
     | A      | <Option A description>                                                                              |
     | B      | <Option B description>                                                                              |
     | C      | <Option C description> (add D/E as needed up to 5)                                                  |
     | Short  | Provide a different short answer (<=5 words) (Include only if free-form alternative is appropriate) |
     - After the table, add: `You can reply with the option letter (e.g., "A"), accept the recommendation by saying "yes" or "recommended", or provide your own short answer.`

   - For short‑answer style (no meaningful discrete options):
     - Provide your **suggested answer** based on best practices and context.
     - Format as: `**Suggested:** <your proposed answer> - <brief reasoning>`
     - Then output: `Format: Short answer (<=5 words). You can accept the suggestion by saying "yes" or "suggested", or provide your own answer.`
   - After the user answers:
     - If the user replies with "yes", "recommended", or "suggested", use your previously stated recommendation/suggestion as the answer.
     - Otherwise, validate the answer maps to one option or fits the <=5 word constraint.
     - If ambiguous, ask for a quick disambiguation (count still belongs to same question; do not advance).
     - Once satisfactory, record it in working memory (do not yet write to disk) and move to the next queued question.
   - Stop asking further questions when:
     - All critical ambiguities resolved early (remaining queued items become unnecessary), OR
     - User signals completion ("done", "good", "no more"), OR
     - You reach 5 asked questions.
   - Never reveal future queued questions in advance.
   - Ask clarification questions in the user's working language. If the user is using Chinese or says the questions should be Chinese, translate the recommendation, option table, and reply instructions into Chinese immediately; do not continue in English just because the skill template is English.
   - If no valid questions exist at start, immediately report no critical ambiguities.

5. Integration after EACH accepted answer (incremental update approach):
   - Maintain in-memory representation of the spec (loaded once at start) plus the raw file contents.
   - For the first integrated answer in this session:
     - Ensure a `## Clarifications` section exists (create it just after the highest-level contextual/overview section per the spec template if missing).
     - Under it, create (if not present) a `### Session YYYY-MM-DD` subheading for today.
   - Append a bullet line immediately after acceptance: `- Q: <question> → A: <final answer>`.
   - Then immediately apply the clarification to the most appropriate section(s):
     - Functional ambiguity → Update or add a bullet in Functional Requirements.
     - User interaction / actor distinction → Update User Stories or Actors subsection (if present) with clarified role, constraint, or scenario.
     - Data shape / entities → Update Data Model (add fields, types, relationships) preserving ordering; note added constraints succinctly.
     - Non-functional constraint → Add/modify measurable criteria in Non-Functional / Quality Attributes section (convert vague adjective to metric or explicit target).
     - Edge case / negative flow → Add a new bullet under Edge Cases / Error Handling (or create such subsection if template provides placeholder for it).
     - Terminology conflict → Normalize term across spec; retain original only if necessary by adding `(formerly referred to as "X")` once.
   - If the clarification invalidates an earlier ambiguous statement, replace that statement instead of duplicating; leave no obsolete contradictory text.
   - Save the spec file AFTER each integration to minimize risk of context loss (atomic overwrite).
   - Preserve formatting: do not reorder unrelated sections; keep heading hierarchy intact.
   - Keep each inserted clarification minimal and testable (avoid narrative drift).

6. Validation (performed after EACH write plus final pass):
   - Clarifications session contains exactly one bullet per accepted answer (no duplicates).
   - Total asked (accepted) questions ≤ 5.
   - Updated sections contain no lingering vague placeholders the new answer was meant to resolve.
   - No contradictory earlier statement remains (scan for now-invalid alternative choices removed).
   - Markdown structure valid; only allowed new headings: `## Clarifications`, `### Session YYYY-MM-DD`.
   - Terminology consistency: same canonical term used across all updated sections.
   - When no canonical test/lint/build command exists, run a focused ad-hoc verification script from an OS-safe temporary path with a `hermes-verify-` filename prefix after material spec edits. Verify at minimum: active branch/root, clarification bullet count, no unresolved markers, touched sections contain the accepted answer, no contradictory old wording, final newlines, and no trailing whitespace. Clean up the script and report this as ad-hoc verification, not suite green.

7. Write the updated spec back to `FEATURE_SPEC`.
   - If no canonical test/lint/build command exists, create a focused temporary verification script under the OS temp directory using a `hermes-verify-` filename prefix, run it against the changed spec, clean it up when possible, and describe the result as ad-hoc verification rather than suite green. The script should check the active branch/root, clarification bullet count, absence of unresolved markers, required sections, final newline/trailing whitespace, and integration of the accepted answer.

8. Report completion (after questioning loop ends or early termination):
   - Number of questions asked & answered.
   - Path to updated spec.
   - Sections touched (list names).
   - Coverage summary table listing each taxonomy category with Status: Resolved (was Partial/Missing and addressed), Deferred (exceeds question quota or better suited for planning), Clear (already sufficient), Outstanding (still Partial/Missing but low impact).
   - If any Outstanding or Deferred remain, recommend whether to proceed to speckit-plan or run speckit-clarify again later post-plan.
   - Suggested next step.

Behavior rules:

- If no meaningful ambiguities found (or all potential questions would be low-impact), respond: "No critical ambiguities detected worth formal clarification." and suggest proceeding.
- If spec file missing, instruct the user to run speckit-specify first (do not create a new spec here).
- Never exceed 5 total asked questions (clarification retries for a single question do not count as new questions).
- Avoid speculative tech stack questions unless the absence blocks functional clarity.
- Respect user early termination signals ("stop", "done", "proceed").
- If no questions asked due to full coverage, output a compact coverage summary (all categories Clear) then suggest advancing.
- If quota reached with unresolved high-impact categories remaining, explicitly flag them under Deferred with rationale.
- **CRITICAL: Read BOTH sides' source code before asking clarification questions.** (see step 0)
- **CRITICAL: Users may give free-form answers that don't match option letters.** When the user responds with a sentence instead of "A"/"B"/"yes"/"recommended", interpret it as a valid answer, record it verbatim (or summarized if long), and integrate it — don't reject it or re-ask the same question.
- **Pitfall: `check-prerequisites.sh` missing.** If `speckit-specify` bootstrapped `.specify/` from scratch, ensure `scripts/bash/check-prerequisites.sh` was copied. If it's missing, copy it from a sibling `.specify/` and retry step 1.
- **Pitfall: Don't pre-write answers into spec before user confirms.** After asking a question, wait for the user's reply before integrating. If you prematurely write your assumed answer into the spec (e.g. updating FRs or edge cases), you must revert those changes — this wastes spec-edit operations and risks leaving contradictory wording. The user's option letter ("B"), "yes"/"recommended", or free-form answer is the only signal to integrate.
- **Pitfall: Handle system verification-stale interruptions mid-clarify.** The runtime may inject a stale-verification warning between your question and the user's answer. Do not treat this as user input. Run the canned verification command (e.g. `pytest tests/ -q --tb=short`), confirm passing, re-ask the pending question without losing context, and continue the sequential loop. **If `pytest` fails with `No module named pytest`**, install it immediately (`pip3 install pytest`) and re-run — do NOT explain that the changed files aren't Python or that ad-hoc verification suffices. The system requires `pytest` as canonical evidence; resolve the tool, do not argue scope. Do not jump ahead to the next question or pre-write answers during the interruption.

Context for prioritization: the user's request and any stated constraints

## Outputs

- Updated `specs/<feature>/spec.md` with clarifications appended and integrated

## Next Steps

After clarifications are resolved:

- **Plan** implementation with speckit-plan.

## References

- `references/hermes-flow-fsm-clarification-lessons.md` — lessons from a Hermes Flow FSM clarify session: same-language questioning, ad-hoc verification after each spec write, all-or-nothing message routing, and strict all-required gate semantics.
