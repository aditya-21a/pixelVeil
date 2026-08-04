# known-issues.md

Every issue gets an ID (`ISSUE-001`, `ISSUE-002`, ...) so it can be referenced precisely — in commit messages, in agent prompts, in TASKS.md. Never reuse a number, even for closed issues — keep them below in a Resolved section for history.

---

## Format (copy this for every new entry)

```
### ISSUE-00X — <short title>
- **Status:** Open / In Progress / Resolved
- **Severity:** Critical / Major / Minor
- **Affected files:** <path(s)>
- **Description:** <what's wrong, observed behavior>
- **Reproduction:** <how to trigger it, if known>
- **Workaround:** <if any exists, else "none">
- **Notes:** <anything relevant — links to related decisions, git commits>
```

---

## Open Issues

*(none yet — add entries here as they're found)*

---

## Resolved Issues

*(move resolved entries here, keep the ID and add a "Resolved in commit: <hash>" line — don't delete history)*