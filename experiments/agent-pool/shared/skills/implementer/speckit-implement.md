---
name: speckit-implement
description: Execute the implementation plan by processing and executing all tasks defined in tasks.md
---

# Spec Kit Implement Skill

## When to Use

- The plan and tasks are complete and you are ready to implement.

## Inputs

- `specs/<feature>/tasks.md` and `plan.md`
- Optional artifacts: `data-model.md`, `contracts/`, `research.md`, `quickstart.md`
- User constraints (e.g., scope, testing expectations)

If the spec is missing, ask the user to run speckit-specify first.

**Setup pitfall**: If `setup-plan.sh` warns "Plan template not found", the project
is missing `参考 template: `. See `references/template-setup-pitfall.md` for
the one-command fix.

**Python path pitfalls**: When implementing a Python project with `src/` package
structure, see `references/python-path-pitfalls.md` for import resolution and
file path patterns that avoid `ModuleNotFoundError` and `FileNotFoundError`.
For flat-package projects (no `src/`), see the **Editable Install** section in
the same file for `pip install -e .` build-backend and package-discovery pitfalls.

**Global state test isolation**: When implementation introduces a module-level
singleton (global tracer, config, registry), see
`references/global-state-test-isolation.md` for the `autouse` fixture pattern
that prevents state leaking across tests.

**Always-on instrumentation patterns**: When implementing always-on
instrumentation (tracer, observer, metrics), see
`references/always-on-instrumentation-patterns.md` for no-op dummy objects,
instrumentation ordering, crash-safe flush, write tolerance, and test isolation.

## Workflow

1. Run `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` from repo root and parse FEATURE_DIR and AVAILABLE_DOCS list. All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. **Check checklists status** (if FEATURE_DIR/checklists/ exists):
   - Scan all checklist files in the checklists/ directory
   - For each checklist, count:
     - Total items: All lines matching `- [ ]` or `- [X]` or `- [x]`
     - Completed items: Lines matching `- [X]` or `- [x]`
     - Incomplete items: Lines matching `- [ ]`
   - Create a status table:

     ```text
     | Checklist | Total | Completed | Incomplete | Status |
     |-----------|-------|-----------|------------|--------|
     | ux.md     | 12    | 12        | 0          | ✓ PASS |
     | test.md   | 8     | 5         | 3          | ✗ FAIL |
     | security.md | 6   | 6         | 0          | ✓ PASS |
     ```

   - Calculate overall status:
     - **PASS**: All checklists have 0 incomplete items
     - **FAIL**: One or more checklists have incomplete items

   - **If any checklist is incomplete**:
     - Display the table with incomplete item counts
     - **STOP** and ask: "Some checklists are incomplete. Do you want to proceed with implementation anyway? (yes/no)"
     - Wait for user response before continuing
     - If user says "no" or "wait" or "stop", halt execution
     - If user says "yes" or "proceed" or "continue", proceed to step 3

   - **If all checklists are complete**:
     - Display the table showing all checklists passed
     - Automatically proceed to step 3

3. Load and analyze the implementation context:
   - **REQUIRED**: Read tasks.md for the complete task list and execution plan
   - **REQUIRED**: Read plan.md for tech stack, architecture, and file structure
   - **IF EXISTS**: Read data-model.md for entities and relationships
   - **IF EXISTS**: Read contracts/ for API specifications and test requirements
   - **IF EXISTS**: Read research.md for technical decisions and constraints
   - **IF EXISTS**: Read quickstart.md for integration scenarios

3a. **Pre-implementation task quality review** (NEW — read tasks.md first, then review):
   Before any setup or coding, scan tasks.md for these common quality issues and fix them. This step prevents wasted work on ambiguous or contradictory task definitions.

   **Checklist**:

   - [ ] **Same-file [P] violations**: Identify all tasks sharing a file where more than one has `[P]`. Fix by removing `[P]` from all but the first task per file, adding a note like "(Not [P] — shares file T020.)". Also update the parallel-examples section to reflect the correct ordering.
   - [ ] **Missing edge-case coverage**: Cross-reference spec edge-cases section, data-model validation rules, and plan.md constraints against the task list. If the tasks don't cover a spec-edge-case or data-model validation rule, add a task for it. (Common misses: timeout/idle-budget enforcement, invalid-input rejection, concurrent-state guards, nullable-terminal-state fields in contracts.)
   - [ ] **Under-specified tasks**: Each task description must name exact file paths and give enough detail that a cheap LLM can implement without asking for clarification. If a task says "Add minimal metadata in pyproject.toml" without specifying what fields, expand it.
   - [ ] **Contract field quality**: Scan contracts/ for fields that are `required` but should be nullable (e.g. `pending_gate` in a terminal status). Fix: remove from `required`, add `anyOf: [<type>, 'null']` or `nullable: true`.
   - [ ] **Documentation formatting**: Scan quickstart.md, README.md, and example files for formatting issues (extra spaces, broken code blocks, inconsistent indentation, backslash continuations with inconsistent spacing). Fix to single-space flag separation, consistent backticks.
   - [ ] **User constraints**: Re-read the user's instruction/request for any scope, quality, or approach preferences they stated. Ensure the task plan respects them. If the user said "no new dependencies", verify tasks don't add unexpected packages.
   - [ ] **UI design approval (frontend tasks only)**: Before writing any HTML/CSS/JS, sketch the layout in ASCII or markdown. Present it to the user for confirmation. Do NOT jump to code — the user will reject a coded implementation if the layout was not agreed first. This rule applies even when the user says "go ahead" — if you have a design in mind, sketch it first and wait for a nod.

   Fix issues in the source files (tasks.md, contracts/, quickstart.md, plan.md) before proceeding to step 4. This is the right moment — the files are fresh and easy to correct.

4. **Project Setup Verification**:
   - **REQUIRED**: Create/verify ignore files based on actual project setup:

   **Detection & Creation Logic**:
   - Check if the following command succeeds to determine if the repository is a git repo (create/verify .gitignore if so):

     ```sh
     git rev-parse --git-dir 2>/dev/null
     ```

   - Check if Dockerfile\* exists or Docker in plan.md → create/verify .dockerignore
   - Check if .eslintrc\* exists → create/verify .eslintignore
   - Check if eslint.config.\* exists → ensure the config's `ignores` entries cover required patterns
   - Check if .prettierrc\* exists → create/verify .prettierignore
   - Check if .npmrc or package.json exists → create/verify .npmignore (if publishing)
   - Check if terraform files (\*.tf) exist → create/verify .terraformignore
   - Check if .helmignore needed (helm charts present) → create/verify .helmignore

   **If ignore file already exists**: Verify it contains essential patterns, append missing critical patterns only
   **If ignore file missing**: Create with full pattern set for detected technology

   **Common Patterns by Technology** (from plan.md tech stack):
   - **Node.js/JavaScript/TypeScript**: `node_modules/`, `dist/`, `build/`, `*.log`, `.env*`
   - **Python**: `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `*.egg-info/`
   - **Java**: `target/`, `*.class`, `*.jar`, `.gradle/`, `build/`
   - **C#/.NET**: `bin/`, `obj/`, `*.user`, `*.suo`, `packages/`
   - **Go**: `*.exe`, `*.test`, `vendor/`, `*.out`
   - **Ruby**: `.bundle/`, `log/`, `tmp/`, `*.gem`, `vendor/bundle/`
   - **PHP**: `vendor/`, `*.log`, `*.cache`, `*.env`
   - **Rust**: `target/`, `debug/`, `release/`, `*.rs.bk`, `*.rlib`, `*.prof*`, `.idea/`, `*.log`, `.env*`
   - **Kotlin**: `build/`, `out/`, `.gradle/`, `.idea/`, `*.class`, `*.jar`, `*.iml`, `*.log`, `.env*`
   - **C++**: `build/`, `bin/`, `obj/`, `out/`, `*.o`, `*.so`, `*.a`, `*.exe`, `*.dll`, `.idea/`, `*.log`, `.env*`
   - **C**: `build/`, `bin/`, `obj/`, `out/`, `*.o`, `*.a`, `*.so`, `*.exe`, `Makefile`, `config.log`, `.idea/`, `*.log`, `.env*`
   - **Swift**: `.build/`, `DerivedData/`, `*.swiftpm/`, `Packages/`
   - **R**: `.Rproj.user/`, `.Rhistory`, `.RData`, `.Ruserdata`, `*.Rproj`, `packrat/`, `renv/`
   - **Universal**: `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.swp`, `.vscode/`, `.idea/`

   **Tool-Specific Patterns**:
   - **Docker**: `node_modules/`, `.git/`, `Dockerfile*`, `.dockerignore`, `*.log*`, `.env*`, `coverage/`
   - **ESLint**: `node_modules/`, `dist/`, `build/`, `coverage/`, `*.min.js`
   - **Prettier**: `node_modules/`, `dist/`, `build/`, `coverage/`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
   - **Terraform**: `.terraform/`, `*.tfstate*`, `*.tfvars`, `.terraform.lock.hcl`
   - **Kubernetes/k8s**: `*.secret.yaml`, `secrets/`, `.kube/`, `kubeconfig*`, `*.key`, `*.crt`

5. Parse tasks.md structure and extract:
   - **Task phases**: Setup, Tests, Core, Integration, Polish
   - **Task dependencies**: Sequential vs parallel execution rules
   - **Task details**: ID, description, file paths, parallel markers [P]
   - **Execution flow**: Order and dependency requirements

6. Execute implementation following the task plan:
   - **Phase-by-phase execution**: Complete each phase before moving to the next
   - **Respect dependencies**: Run sequential tasks in order, parallel tasks [P] can run together
   - **Follow TDD approach**: Execute test tasks before their corresponding implementation tasks
   - **File-based coordination**: Tasks affecting the same files must run sequentially
   - **Validation checkpoints**: Verify each phase completion before proceeding

7. Implementation execution rules:
   - **Setup first**: Initialize project structure, dependencies, configuration
   - **Tests before code**: If you need to write tests for contracts, entities, and integration scenarios
   - **Core development**: Implement models, services, CLI commands, endpoints
   - **Integration work**: Database connections, middleware, logging, external services
   - **Polish and validation**: Unit tests, performance optimization, documentation

8. Progress tracking and error handling:
   - Report progress after each completed task
   - After marking any task [x], verify no duplicate unchecked task IDs remain: `grep -c '\[ \]' specs/<feature>/tasks.md` (should be decreasing) and `grep -oP 'T\d+' specs/<feature>/tasks.md | sort | uniq -d` (should be empty). Duplicates happen when a task ID appears in both an old unchecked location and a newly checked location after patching across section boundaries.
   - Run the canonical verification command (e.g. `pytest`) after EACH file write that modifies source code. The system may fire stale-verification warnings mid-implement; running the test command immediately after each edit pre-empts these interruptions and avoids breaking the flow.
   - Halt execution if any non-parallel task fails
   - For parallel tasks [P], continue with successful tasks, report failed ones
   - Provide clear error messages with context for debugging
   - Suggest next steps if implementation cannot proceed
   - **IMPORTANT** For completed tasks, make sure to mark the task off as [X] in the tasks file.

9. Completion validation:
   - Verify all required tasks are completed
   - Check that implemented features match the original specification
   - Validate that tests pass and coverage meets requirements
   - Confirm the implementation follows the technical plan
   - Report final status with summary of completed work

Note: This skill assumes a complete task breakdown exists in tasks.md. If tasks are incomplete or missing, suggest running speckit-tasks first to regenerate the task list.

## References

- `references/fsm-engine-impl-pitfalls.md` — Common mistakes when implementing FSM engines (round counter exhaustion, decision filtering, store method signatures, mock objects), collected from real implementation sessions.
- `references/agent-loop-impl-pitfalls.md` — Pitfalls in RuntimeLoop implementation: SQLite thread safety, double-recorded decisions, context packet missing round counter, two dispatch modes (state entry vs inbox-driven), sender permission checks, delegate mode broker requirements, agent runner mode separation.
- `references/agent-communication-pattern.md` — Message_send generation in agent_runner, personality-driven rejection logic, multi-actor flow YAML design, infinite-loop prevention (reviewer must concede after N rounds), and sequence diagram representation of messages/decisions/tool-calls.
- `references/sequence-diagram-pattern.md` — Replacing linear state DAG with interactive sequence diagram: lifeline layout, event classification (tool_call/decision/message/transition), dot visual design by type, SVG arrow overlay for messages and decisions, clickable dots/arrows for details, active agent highlighting.
- `references/sseserver-threading-pitfall.md` — `http.server.HTTPServer` blocks all API requests when an SSE stream is active. Fix: use `ThreadingHTTPServer`. Applies to any project adding a real-time dashboard with SSE streaming.
- `references/sqlite-schema-migration.md` — Adding columns to existing SQLite databases. The two-part fix: update `SCHEMA_SQL` for new databases + `ALTER TABLE ADD COLUMN` with try/except in `init_schema()` for existing databases.

## Outputs

- Implementation changes in the codebase
- Updated `specs/<feature>/tasks.md` with completed tasks checked off
- Any generated/updated ignore files (e.g., `.gitignore`, `.dockerignore`, `.eslintignore`, `.prettierignore`)
