# AGENTS.md — Read This First, Every Session

You are working on **PixelVeil** — a local Windows desktop app that redacts faces and PII text from screen recordings. Solo developer, uses AI agents across many sessions/tools. This file is the operating manual. Follow it exactly. Do not skip steps to save time — skipping steps here is what burns the developer's tokens and money on the *next* session cleaning up after you.

---

## 0. The Prime Rule

**Never guess about project history, past decisions, or why something is built a certain way. Read the docs. If the answer isn't in the docs, say so explicitly instead of assuming.** A wrong assumption written into code costs far more (tokens, time, developer trust) than a five-minute doc read.

---

## 1. Session Start Protocol — Do This Before Writing Any Code

Read, in this order:
1. `AGENTS.md` (this file)
2. `docs/current-state.md` — what's actually working right now, as of the last session
3. `docs/known-issues.md` — don't re-discover a known bug and burn tokens "fixing" it wrong, or duplicate an existing issue entry
4. `docs/DECISIONS.md` — **only read the specific entries relevant to your task**, not the whole file every time, unless the task is broad/architectural
5. `docs/TASKS.md` — find your specific task, confirm its dependencies are marked done

Do **not** re-read `docs/roadmap.md`, `docs/architecture.md`, `docs/design.md`, or `docs/TESTING.md` in full every session — those are stable reference docs. Only pull the specific section relevant to your current task. Re-reading everything every time is exactly the kind of token waste this file exists to prevent.

**If given a specific bug/issue to fix**, you will be told to read a narrower set — follow that instruction exactly, don't expand scope on your own.

---

## 2. Scope Discipline — Non-Negotiable

- **Only touch files relevant to your assigned task.** Do not refactor, "clean up," or rewrite unrelated code you happen to notice, even if it looks wrong to you. If you spot a real problem outside your task, log it in `docs/known-issues.md` instead of fixing it — the developer decides priority, not you.
- **Do not change the tech stack, library choices, or architecture** without the developer explicitly asking for it. Every stack choice in this repo was already deliberated — see `docs/DECISIONS.md`. If you think a decision was wrong, say so and explain why, but do not silently override it.
- **v1 scope is locked.** Do not add features from the v2 backlog (age/child detection, batch processing, live redaction, extension, web app) unless explicitly asked. Check `docs/roadmap.md` and `docs/TASKS.md` if unsure what's in v1.
- **Respect the module boundaries** in `docs/structure.md` — `core/` has zero UI dependencies, `webtest/` and `gui/` are separate interfaces over the same `core/` pipeline. Don't blur this line for convenience.

---

## 3. While Working

- Prefer the smallest correct change over a large rewrite. If a function is stubbed with `raise NotImplementedError`, implement it — don't restructure the whole file "while you're in there."
- If you hit a genuine ambiguity not resolved by the docs (e.g. an edge case `docs/TESTING.md` doesn't cover), make a reasonable call, implement it, and **log the decision and reasoning** per section 5 below — don't leave it silently undocumented.
- If a task turns out to depend on something not yet built, stop and say so rather than stubbing around it in a way that hides the gap.

---

## 4. Git Commit Discipline

Every meaningful change gets its own commit, using **Conventional Commits** format:

```
<type>: <short description>

<optional longer body if the change needs explanation>
```

**Types to use:**
- `feat:` — new functionality
- `fix:` — bug fix
- `perf:` — performance improvement
- `docs:` — documentation-only changes
- `test:` — adding/updating tests
- `chore:` — tooling, dependencies, non-functional changes
- `refactor:` — restructuring code with no behavior change (use sparingly, and only within your task's scope)

**Examples:**
```
feat: add OCR-based email detection
fix: prevent overlapping face blur regions
perf: cache OCR results between similar frames
feat: add persistent user redaction zones
fix: preserve audio during video export
docs: update current-state.md after OCR detector implementation
```

**Why this matters:** `git log --oneline -20` or `git log --oneline -- core/video_pipeline.py` becomes a fast, cheap way for a future agent (or you) to understand recent history without reading through every markdown doc. Git is a memory layer, not just version control — treat commit messages as documentation, not an afterthought.

Commit **after each logically complete change**, not one giant commit at the end of a session.

---

## 5. Session End Protocol — Do Every Item, Every Session

Before you finish and hand back control, in this order:

1. **Run relevant tests** (`tests/` — at minimum the tests touching files you changed).
2. **Update `docs/current-state.md`** if project behavior changed — this file must always reflect reality, not aspiration.
3. **Update `docs/TASKS.md`** — check off what's done, add any new subtasks you discovered.
4. **Update `docs/known-issues.md`** for anything unresolved — new issues found, or existing issues whose status changed.
5. **Update `docs/DECISIONS.md`** — but *only* if you made an actual architectural/technical decision (a real fork in the road with reasoning), not for routine implementation choices.
6. **Add a short entry to `docs/development-log.md`** — a few lines, not a narrative (see format in that file).
7. **Do not duplicate information across docs.** If something belongs in `current-state.md`, it doesn't also need a paragraph in `development-log.md` — cross-reference instead of copying.
8. **Commit your work with a properly formatted message** (section 4).

If you skip this checklist, the next session — possibly a different agent entirely — starts from a stale or inaccurate picture of the project, which costs the developer real money re-diagnosing things you already knew.

---

## 6. When Something Is Broken (Bug-Fix Sessions)

The developer will typically hand you a narrow prompt like:

```
Read:
- AGENTS.md
- docs/current-state.md
- docs/known-issues.md
- docs/DECISIONS.md (only entries relevant to the affected component)

Then investigate ISSUE-00X.

Use git history where necessary (git log --oneline -- <file>).
Do not modify unrelated components.
```

Follow that literally. Do not ask the developer to re-explain project history — everything you need is in those files and in git log. If it's genuinely not there, say exactly what's missing rather than guessing.

**Investigation order for a bug:**
1. Read the issue entry in `docs/known-issues.md` fully.
2. Check `git log --oneline -- <affected file(s)>` for relevant recent changes.
3. Reproduce or trace the issue in the narrowest possible scope.
4. Fix only what's needed to resolve the specific issue.
5. Update the issue's status in `docs/known-issues.md` (resolved / still open / partially resolved, with a note).
6. Follow the full Session End Protocol (section 5).

---

## 7. Token/Cost Discipline (Explicit, Because This Matters to the Developer)

- Don't read entire files when you only need one function — use targeted reads where your tooling allows it.
- Don't re-explain the whole project back to the developer unless asked — assume they know their own project; report only what changed or what you found.
- Don't regenerate working code "for clarity" — leave correct, working code alone.
- Don't ask the developer questions answerable from the docs already in the repo — read first, ask only genuine ambiguities.
- If a task is large, break it into the smallest committable pieces rather than one long uninterrupted session — this keeps git history useful and keeps any single session's blast radius small if something goes wrong.

---

## 8. Documentation Map (What Lives Where — Don't Duplicate)

| File | Purpose | Update frequency |
|---|---|---|
| `AGENTS.md` | This file — process rules | Rarely (developer edits directly) |
| `docs/roadmap.md` | Product scope, USP, pricing, target buyer | Rarely — only on real scope changes |
| `docs/architecture.md` | Tech stack + reasoning, data flow | Rarely — only on real stack changes |
| `docs/design.md` | UI layout spec (test harness) | Rarely |
| `docs/structure.md` | Folder/file layout and why | Rarely |
| `docs/DECISIONS.md` | Log of architectural decisions + why | On real decisions only |
| `docs/TASKS.md` | Granular implementation checklist | Every session |
| `docs/current-state.md` | **What's actually working right now** — the single source of truth for "where are we" | Every session, if behavior changed |
| `docs/known-issues.md` | Open bugs/limitations, tracked by ID | Every session, as needed |
| `docs/development-log.md` | Short chronological log of what changed, session by session | Every session |
| `docs/TESTING.md` | Test strategy and acceptance criteria | Rarely — only if test strategy changes |
| `CHANGELOG.md` | User-facing version history (once versions ship) | On each release, not every session |

**The distinction that matters most:** `development-log.md` is *internal, for agents/developer* — short technical breadcrumbs. `CHANGELOG.md` is *external, for end users* — what changed between released versions. Don't mix these.

---

## 9. If You're Ever Unsure Whether to Proceed

Stop and state the ambiguity plainly rather than picking a guess and running with it silently. A clarifying question that costs one exchange is far cheaper than a wrong implementation that has to be found, diagnosed, and unwound in a later session.