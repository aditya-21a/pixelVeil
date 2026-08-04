# PixelVeil — AI Agent Prompt Templates (VS Code Edition)

## How to Use

Use your AI coding tool's context/file-reference feature instead of pasting entire files into chat.

Examples:

`@AGENTS.md`  
`@docs/current-state.md`  
`@docs/tasks.md`  
`@core/pii_matcher.py`

For normal development sessions, always provide:

- `@AGENTS.md`
- `@docs/current-state.md`

Then provide only the additional files required by the specific task.

Do not attach the entire `docs/` directory unless genuinely necessary.

---

## 0. Initial Scaffold

> Use only when creating/recreating the project structure from scratch.

**Context Files:**

- `@AGENTS.md`
- `@docs/architecture.md`
- `@docs/structure.md`

**Prompt:**

Task: Create the initial PixelVeil project scaffold exactly as defined in `docs/structure.md`.

Requirements:

1. Create `requirements.txt` containing the required core dependencies.
2. Create the directory/file structure defined in `docs/structure.md`.
3. Add only minimal placeholders where implementation does not yet exist.

Constraints:

- Do not implement Phase 1 functionality.
- Do not introduce dependencies not already approved by the project documentation.
- Do not create additional files or directories unless required.
- Follow `AGENTS.md`.

---

## 1. New Task / Feature

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/tasks.md`
- `@<specific_affected_files>`
- Relevant section of `@docs/decisions.md` only if needed

**Prompt:**

Task: Implement `<exact task>` from `docs/tasks.md`.

Constraints:

- Touch only files required for this task.
- Do not refactor or improve unrelated code.
- Do not add functionality beyond the task.
- Follow existing architecture and conventions.
- Do not introduce new dependencies without asking first.
- Run the relevant tests after implementation.
- If documentation contradicts the actual implementation, report the discrepancy instead of silently assuming which is correct.
- Follow the Session End Protocol in `AGENTS.md`.
- Do not create a Git commit unless I explicitly ask.

---

## 2. Known Bug

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/known-issues.md`
- `@<affected_code_files>`
- Relevant test file(s)

**Prompt:**

Task: Investigate and fix `ISSUE-XXX` as described in `docs/known-issues.md`.

Constraints:

- Fix only this issue.
- Prefer the smallest correct change.
- Do not modify unrelated components.
- Check existing tests before changing behavior.
- Add or update a regression test when appropriate.
- Run relevant tests after the fix.
- If history is needed, inspect Git history before asking me to explain previous changes.
- Update the issue status in `docs/known-issues.md`.
- Follow the Session End Protocol in `AGENTS.md`.
- Do not create a Git commit unless I explicitly ask.

---

## 3. New / Undocumented Bug

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/known-issues.md`
- `@<affected_code_files>`
- Relevant test file(s)

**Prompt:**

Bug: `<exact description>`

Reproduction:

`<steps to reproduce>`

Task:

1. Add this bug to `docs/known-issues.md` using the existing format and next available `ISSUE-XXX` ID.
2. Investigate the cause.
3. Fix only what is necessary.
4. Add or update a regression test when appropriate.
5. Run relevant tests.
6. Update the issue status after verification.

Do not refactor unrelated code.

Follow the Session End Protocol in `AGENTS.md`.

Do not create a Git commit unless I explicitly ask.

---

## 4. Small Contained Fix

> Use only for genuinely trivial, isolated fixes. Do not use for pipeline behavior, detection accuracy, architecture, dependencies, or multi-file changes.

**Context Files:**

- `@<single_affected_file>`
- Relevant test file if one exists

**Prompt:**

Task: Fix `<exact trivial issue>`.

Constraints:

- Make the smallest possible change.
- Do not refactor unrelated code.
- Do not modify other files unless required.
- Run the relevant test if one exists.
- Do not update project documentation unless this changes documented behavior.
- Do not create a Git commit.

When finished, give me a one-line Conventional Commits-format commit message.

---

## 5. Writing / Expanding Tests

**Context Files:**

- `@AGENTS.md`
- Relevant section of `@docs/testing.md`
- `@<file_to_test>`
- `@<existing_relevant_test_file>`

**Prompt:**

Task: Write tests for `<specific function/module>`.

Constraints:

- Follow the relevant acceptance criteria and testing philosophy in `docs/testing.md`.
- Match the style of existing tests.
- Test only the requested functionality.
- Include important edge cases relevant to this functionality.
- Do not modify production behavior merely to make tests pass unless an actual bug is discovered.
- Run the relevant tests after implementation.
- Follow the Session End Protocol in `AGENTS.md`.
- Do not create a Git commit unless I explicitly ask.

---

## 6. Architecture / Decision Question

**Context Files:**

- `@AGENTS.md`
- Relevant entries from `@docs/decisions.md`
- Relevant section of `@docs/architecture.md`
- Relevant affected source files if necessary

**Prompt:**

Question: `<question or proposed architectural change>`

Evaluate the proposal against the existing architecture and decisions.

If a new architectural decision is required:

1. State the proposed decision.
2. Explain why it is needed.
3. Explain the tradeoffs.
4. List alternatives considered.
5. Identify affected components/files.
6. State whether an existing decision would be replaced or superseded.

Do not modify code.

Wait for my explicit approval before implementing any architectural, stack, dependency, or major design change.

---

## 7. Resume / Agent Handoff

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/tasks.md`
- `@docs/known-issues.md`
- `@<affected_files>`

**Prompt:**

Task: Continue unfinished work from a previous session.

Handoff state:

`<exactly what was completed, what remains, and where work stopped>`

Constraints:

- Continue only from the known handoff point.
- Inspect the provided implementation before making changes.
- Do not redo completed work.
- Do not assume undocumented implementation details.
- If documentation and code disagree, report the discrepancy before making a decision that depends on it.
- Use Git history if previous implementation context is needed.
- Run relevant tests when finished.
- Follow the Session End Protocol in `AGENTS.md`.
- Do not create a Git commit unless I explicitly ask.

---

## 8. Resume After Long Break

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/tasks.md`
- `@docs/known-issues.md`

**Prompt:**

Do not implement anything yet.

Summarize the project state in no more than 5 lines:

1. What currently works.
2. What is partially implemented.
3. What the next task is.
4. Which issues are `Open` or `In Progress`.
5. What I should work on next.

Do not inspect unrelated source files unless the documentation contains a clear contradiction that prevents this summary.

---

## 9. Review Before Commit

**Context Files:**

- Relevant section of `@AGENTS.md`
- Changed files or current Git diff

**Prompt:**

Review the current changes before commit.

Check only for:

- Accidental unrelated changes
- Obvious correctness problems
- Missing relevant tests
- Documentation that must be updated under `AGENTS.md`
- Files that should not be committed

Do not refactor or expand the implementation.

Then provide the appropriate Conventional Commits-format commit message.

Do not create the commit yourself.

---

## 10. End-of-Session Wrap-Up

**Context Files:**

- `@AGENTS.md`
- `@docs/current-state.md`
- `@docs/tasks.md`
- `@docs/known-issues.md`
- `@docs/development-log.md`
- `@docs/decisions.md` only if an architectural decision was made

**Prompt:**

Task: Perform the Session End Protocol from `AGENTS.md`.

Based only on work actually completed during this session:

1. Update `docs/current-state.md` if implementation state changed.
2. Update `docs/tasks.md` for completed, active, or newly discovered work.
3. Update `docs/known-issues.md` if issue status changed or a new unresolved issue was discovered.
4. Add a concise entry to `docs/development-log.md`.
5. Update `docs/decisions.md` only if a genuine architectural decision was made.

Do not duplicate information unnecessarily between documents.

Do not mark anything complete unless it was implemented and verified.

Run relevant tests before finalizing the session.

Then report:

- Tests run and result
- Documentation updated
- Remaining issue/task, if any
- Conventional Commits-format commit message(s)

If the work contains logically separate changes, suggest separate commits.

Do not create Git commits unless I explicitly ask.