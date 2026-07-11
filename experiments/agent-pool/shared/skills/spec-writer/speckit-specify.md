---
name: speckit-specify
description: Create or update a feature specification from a natural language feature description.
---

# Spec Kit Specify Skill

## When to Use

- The user wants a new or updated feature spec from a natural language description.

## Inputs

- Feature description from the user.
- Repo context with `.specify/` scripts and templates.

If the description is missing or unclear, ask a targeted question before continuing.

## Bootstrapping `.specify/` (when missing)

When the project root has no `.specify/` directory, bootstrap it BEFORE proceeding:

1. Search for an existing `.specify/` in sibling repos (e.g., `~/.runtime-trace/runtime-trace-agent/.specify/`).
2. Copy the entire `.specify/` tree, or at minimum these files:
   - `scripts/bash/create-new-feature.sh`
   - `scripts/bash/common.sh`
   - `scripts/bash/check-prerequisites.sh`
   - `templates/spec-template.md`
   - `templates/checklist-template.md`
   - `init-options.json`
3. If the project has no git repo, run `git init` (the create-new-feature script requires git for branch creation).
4. Verify: `.specify/scripts/bash/create-new-feature.sh --help` exits 0.

Pitfall: copying only `create-new-feature.sh` + `common.sh` is insufficient — `speckit-clarify` needs `check-prerequisites.sh` and both skills need the templates. Copy the full tree or the explicit minimum list above.

Pitfall: the verification system may interrupt mid-workflow demanding `pytest` even when changed files are markdown specs/checklists (not Python code). It ignores ad-hoc verification and insists on `pytest` as canonical evidence. Install pytest before or at the first verification step: `pip3 install pytest` (use the project's Python, not system Python if they differ). Then run `pytest tests/ -q --tb=short`. Do NOT explain that the files aren't Python — the system doesn't accept that argument. Resolve the tool and move on.

Pitfall: when removing files identified as dead code (zero imports/references), check for dependent test files by searching import references (`search_files` for the module name in `*.py` files). If tests import the deleted module, remove them in the same operation to avoid pytest collection failure. Example: deleting `runtime_trace/context.py` requires also deleting `tests/runtime_trace/test_context_projection.py`.

## Workflow

The user's feature description in the request **is** the input. Do not ask them to repeat it unless it is missing.

Given that feature description, do this:

1. **Generate a concise short name** (2-4 words) for the branch:
   - Analyze the feature description and extract the most meaningful keywords
   - Create a 2-4 word short name that captures the essence of the feature
   - Use action-noun format when possible (e.g., "add-user-auth", "fix-payment-bug")
   - Preserve technical terms and acronyms (OAuth2, API, JWT, etc.)
   - Keep it concise but descriptive enough to understand the feature at a glance
   - Examples:
     - "I want to add user authentication" → "user-auth"
     - "Implement OAuth2 integration for the API" → "oauth2-api-integration"
     - "Create a dashboard for analytics" → "analytics-dashboard"
     - "Fix payment processing timeout bug" → "fix-payment-timeout"

2. **Check for existing branches before creating new one**:

   a. First, fetch all remote branches to ensure we have the latest information:

   ```bash
   git fetch --all --prune
   ```

   b. Find the highest feature number across all sources for the short-name:
   - Remote branches: `git ls-remote --heads origin | grep -E 'refs/heads/[0-9]+-<short-name>$'`
   - Local branches: `git branch | grep -E '^[* ]*[0-9]+-<short-name>$'`
   - Specs directories: Check for directories matching `specs/[0-9]+-<short-name>`

   c. Determine the next available number:
   - Extract all numbers from all three sources
   - Find the highest number N
   - Use N+1 for the new branch number

   d. Run the script `.specify/scripts/bash/create-new-feature.sh --json "<feature description>"` with the calculated number and short-name:
   - Pass `--number N+1` and `--short-name "your-short-name"` along with the feature description
   - Bash example: `.specify/scripts/bash/create-new-feature.sh --json --number 5 --short-name "user-auth" "Add user authentication"`
   - PowerShell example: `.specify/scripts/bash/create-new-feature.sh -Json -Number 5 -ShortName "user-auth" "Add user authentication"`

   **IMPORTANT**:
   - Check all three sources (remote branches, local branches, specs directories) to find the highest number
   - Only match branches/directories with the exact short-name pattern
   - If no existing branches/directories found with this short-name, start with number 1
   - You must only ever run this script once per feature
   - The JSON is provided in the terminal as output - always refer to it to get the actual content you're looking for
   - The JSON output will contain BRANCH_NAME and SPEC_FILE paths
   - For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot")

3. Load `.specify/templates/spec-template.md` to understand required sections.

4. Follow this execution flow:
   1. Parse user description from Input
      If empty: ERROR "No feature description provided"
   2. Extract key concepts from description
      Identify: actors, actions, data, constraints
   3. For unclear aspects:
      - Make informed guesses based on context and industry standards
      - Only mark with [NEEDS CLARIFICATION: specific question] if:
        - The choice significantly impacts feature scope or user experience
        - Multiple reasonable interpretations exist with different implications
        - No reasonable default exists
      - **LIMIT: Maximum 3 [NEEDS CLARIFICATION] markers total**
      - Prioritize clarifications by impact: scope > security/privacy > user experience > technical details
   4. Fill User Scenarios & Testing section
      If no clear user flow: ERROR "Cannot determine user scenarios"
   5. Generate Functional Requirements
      Each requirement must be testable
      Use reasonable defaults for unspecified details (document assumptions in Assumptions section)
   6. Define Success Criteria
      Create measurable, technology-agnostic outcomes
      Include both quantitative metrics (time, performance, volume) and qualitative measures (user satisfaction, task completion)
      Each criterion must be verifiable without implementation details
   7. Identify Key Entities (if data involved)
   8. Return: SUCCESS (spec ready for planning)

5. Write the specification to SPEC_FILE using the template structure, replacing placeholders with concrete details derived from the feature description (arguments) while preserving section order and headings.

6. **Specification Quality Validation**: After writing the initial spec, validate it against quality criteria:

   a. **Create Spec Quality Checklist**: Generate a checklist file at `FEATURE_DIR/checklists/requirements.md` using the checklist template structure with these validation items:

   ```markdown
   # Specification Quality Checklist: [FEATURE NAME]

   **Purpose**: Validate specification completeness and quality before proceeding to planning
   **Created**: [DATE]
   **Feature**: [Link to spec.md]

   ## Content Quality

   - [ ] No implementation details (languages, frameworks, APIs)
   - [ ] Focused on user value and business needs
   - [ ] Written for non-technical stakeholders
   - [ ] All mandatory sections completed

   ## Requirement Completeness

   - [ ] No [NEEDS CLARIFICATION] markers remain
   - [ ] Requirements are testable and unambiguous
   - [ ] Success criteria are measurable
   - [ ] Success criteria are technology-agnostic (no implementation details)
   - [ ] All acceptance scenarios are defined
   - [ ] Edge cases are identified
   - [ ] Scope is clearly bounded
   - [ ] Dependencies and assumptions identified

   ## Feature Readiness

   - [ ] All functional requirements have clear acceptance criteria
   - [ ] User scenarios cover primary flows
   - [ ] Feature meets measurable outcomes defined in Success Criteria
   - [ ] No implementation details leak into specification

   ## Notes

   - Items marked incomplete require spec updates before the speckit-clarify or speckit-plan skills
   ```

   b. **Run Validation Check**: Review the spec against each checklist item:
   - For each item, determine if it passes or fails
   - Document specific issues found (quote relevant spec sections)

   c. **Handle Validation Results**:
   - **If all items pass**: Mark checklist complete and proceed to step 6

   - **If items fail (excluding [NEEDS CLARIFICATION])**:
     1. List the failing items and specific issues
     2. Update the spec to address each issue
     3. Re-run validation until all items pass (max 3 iterations)
     4. If still failing after 3 iterations, document remaining issues in checklist notes and warn user

   - **If [NEEDS CLARIFICATION] markers remain**:
     1. Extract all [NEEDS CLARIFICATION: ...] markers from the spec
     2. **LIMIT CHECK**: If more than 3 markers exist, keep only the 3 most critical (by scope/security/UX impact) and make informed guesses for the rest
     3. For each clarification needed (max 3), present options to user in this format:

        ```markdown
        ## Question [N]: [Topic]

        **Context**: [Quote relevant spec section]

        **What we need to know**: [Specific question from NEEDS CLARIFICATION marker]

        **Suggested Answers**:

        | Option | Answer                    | Implications                          |
        | ------ | ------------------------- | ------------------------------------- |
        | A      | [First suggested answer]  | [What this means for the feature]     |
        | B      | [Second suggested answer] | [What this means for the feature]     |
        | C      | [Third suggested answer]  | [What this means for the feature]     |
        | Custom | Provide your own answer   | [Explain how to provide custom input] |

        **Your choice**: _[Wait for user response]_
        ```

     4. **CRITICAL - Table Formatting**: Ensure markdown tables are properly formatted:
        - Use consistent spacing with pipes aligned
        - Each cell should have spaces around content: `| Content |` not `|Content|`
        - Header separator must have at least 3 dashes: `|--------|`
        - Test that the table renders correctly in markdown preview
     5. Number questions sequentially (Q1, Q2, Q3 - max 3 total)
     6. Present all questions together before waiting for responses
     7. Wait for user to respond with their choices for all questions (e.g., "Q1: A, Q2: Custom - [details], Q3: B")
     8. Update the spec by replacing each [NEEDS CLARIFICATION] marker with the user's selected or provided answer
     9. Re-run validation after all clarifications are resolved

   d. **Update Checklist**: After each validation iteration, update the checklist file with current pass/fail status

7. Verify generated artifacts before reporting:
   - **PITFALL — Install pytest upfront.** The verification system may interrupt mid-workflow demanding `pytest`. Even when changed files are markdown specs/checklists (not Python code), the system ignores ad-hoc verification and insists on `pytest` as canonical evidence. **Install it before or at the first verification step**: `pip3 install pytest` (use the project's Python, not system Python if they differ). Then run `pytest tests/ -q --tb=short`. If pytest fails with module-not-found, install and re-run — do NOT explain that the files aren't Python. Resolve the tool, do not argue scope.
   - Confirm the current project root is the intended repo root. If `git rev-parse --show-toplevel` points to a parent directory such as the user home, initialize or use a nested repo at the project root before running feature scripts.
   - **PITFALL: The `create-new-feature.sh` script may print `BRANCH_NAME` in the JSON output but NOT actually create the git branch.** This is a known quirk in some git/script setups. Always verify with `git branch --list` (NOT `git branch -a`, which can show stale remote-tracking entries) and `git show-ref --heads`. If `git checkout <branchname>` fails with `pathspec did not match any file`, the branch genuinely does not exist. Create it manually: `git checkout -b <branchname>`. After creating, confirm `git branch --show-current` returns the correct branch name before proceeding.
   - **PITFALL — Dead code cleanup requires test synchronization.** When removing files identified as unused/unreferenced, check for dependent test files by searching import references (`search_files` for the module name in `*.py` files). If tests import the deleted module, remove them in the same operation to avoid pytest collection failure. Example: deleting `runtime_trace/context.py` requires also deleting `tests/runtime_trace/test_context_projection.py`.
   - If no canonical test/lint/build command exists, run a focused ad-hoc verification script from an OS-safe temporary path with a `runtime-trace-verify-` filename prefix.
   - If no canonical test/lint/build command exists, run a focused ad-hoc verification script from an OS-safe temporary path with a `runtime-trace-verify-` filename prefix. If the runtime/system gives a specific temp directory, use that exact directory rather than generic `/tmp`. Check the changed spec/checklist for required sections, no `[NEEDS CLARIFICATION]`, no unresolved template placeholders, completed checklist items, no implementation-detail leakage, final newlines, and no trailing whitespace. Clean up the temporary script and report this as ad-hoc verification, not suite green.
   - Treat any edit after verification as invalidating the evidence. If the verifier finds a spec/checklist issue and you patch it, rerun a fresh `runtime-trace-verify-*` ad-hoc script from the required temp location and only then report completion.

### Translating or exporting an existing spec

When the user asks to translate, copy, or export an existing `spec.md` for reading:

1. Locate the intended source spec, preferring the most recently modified project spec over templates or older desktop copies when the user does not name a path.
2. Read the full live source immediately before writing the translated/exported file; do not rely on an earlier partial read because specs may change mid-session.
3. Preserve structural identifiers exactly: feature branch, user-story count/order, acceptance scenario numbering, FR/TV/SC IDs, key entity names, and clarification entries.
4. After writing, run an ad-hoc `runtime-trace-verify-*` script from the required temp directory that compares source vs target counts/IDs and checks for untranslated placeholders. If verification fails because the source changed, re-read the live source, patch the target, and rerun a fresh verifier.
5. Report this as translation/export ad-hoc verification, not suite green.

8. Report completion with branch name, spec file path, checklist results, verification type/results, and readiness for the next phase (speckit-clarify or speckit-plan).

**NOTE:** The script is intended to create/check out the new branch and initialize the spec file, but still verify the branch from live git state before finalizing.

## Outputs

- `specs/<feature>/spec.md`
- `specs/<feature>/checklists/requirements.md`
- New feature branch created by `.specify/scripts/bash/create-new-feature.sh`

## Next Steps

After generating the spec:

- **Clarify** requirements with speckit-clarify.
- **Plan** implementation with speckit-plan.

## General Guidelines

## Quick Guidelines

- Focus on **WHAT** users need and **WHY**.
- Avoid HOW to implement (no tech stack, APIs, code structure).
- Written for business stakeholders, not developers.
- DO NOT create any checklists that are embedded in the spec. That will be a separate skill.

### Section Requirements

- **Mandatory sections**: Must be completed for every feature
- **Optional sections**: Include only when relevant to the feature
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

### For AI Generation

When creating this spec from a user prompt:

1. **Make informed guesses**: Use context, industry standards, and common patterns to fill gaps
2. **Document assumptions**: Record reasonable defaults in the Assumptions section
3. **Limit clarifications**: Maximum 3 [NEEDS CLARIFICATION] markers - use only for critical decisions that:
   - Significantly impact feature scope or user experience
   - Have multiple reasonable interpretations with different implications
   - Lack any reasonable default
4. **Prioritize clarifications**: scope > security/privacy > user experience > technical details
5. **Think like a tester**: Every vague requirement should fail the "testable and unambiguous" checklist item
6. **Common areas needing clarification** (only if no reasonable default exists):
   - Feature scope and boundaries (include/exclude specific use cases)
   - User types and permissions (if multiple conflicting interpretations possible)
   - Security/compliance requirements (when legally/financially significant)

**Examples of reasonable defaults** (don't ask about these):

- Data retention: Industry-standard practices for the domain
- Performance targets: Standard web/mobile app expectations unless specified
- Error handling: User-friendly messages with appropriate fallbacks
- Authentication method: Standard session-based or OAuth2 for web apps
- Integration patterns: RESTful APIs unless specified otherwise

### Success Criteria Guidelines

Success criteria must be:

1. **Measurable**: Include specific metrics (time, percentage, count, rate)
2. **Technology-agnostic**: No mention of frameworks, languages, databases, or tools
3. **User-focused**: Describe outcomes from user/business perspective, not system internals
4. **Verifiable**: Can be tested/validated without knowing implementation details

**Good examples**:

- "Users can complete checkout in under 3 minutes"
- "System supports 10,000 concurrent users"
- "95% of searches return results in under 1 second"
- "Task completion rate improves by 40%"

**Bad examples** (implementation-focused):

- "API response time is under 200ms" (too technical, use "Users see results instantly")
- "Database can handle 1000 TPS" (implementation detail, use user-facing metric)
- "React components render efficiently" (framework-specific)
- "Redis cache hit rate above 80%" (technology-specific)
