# Step N: <name>

Copy this file to `docs/steps/step-N.md` and fill in every section. Keep it short: tables, bullets and real output, not prose. Write "none" where a section is empty.

## Summary

| | |
|---|---|
| **Built** | One line |
| **Status** | in progress · waiting for review · approved |
| **Blocked on** | nothing |
| **Date** | YYYY-MM-DD |
| **Agent(s)** | Who worked on it (e.g. Claude Opus 5.5 main · Codex reviewer) |

## Design
- What this step adds and why, in 3–5 bullets.
- One diagram or table if it helps. Bake mermaid before handing over.

## Files changed

| File | Change | Why |
|---|---|---|
| `src/...` | added / changed | |

Review the full change, new files included: `.review/step-N/round-K.diff` (written by `tools/review.sh`, TESTING §12.3) before commit, or `git show <commit>` after.

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| | | |

```text
<paste the last lines of make check>
<paste the last lines of make sanitize>
<paste the last lines of make check-data (from step 2 on)>
```

## Review (Codex)

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | | fixed / not fixed because ... |

Left for the developer to decide: none

## Review (Claude skeptic, separate agent)

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | | fixed / not fixed because ... |

## Proof the tests catch bugs

| Deliberate break (in a scratch copy) | Test that failed |
|---|---|
| | |

The code was restored exactly afterwards: yes / no

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `command` or URL to open | | |

## Deploy (from step 5b, after approval)

| Command | Smoke test | Rolled back? |
|---|---|---|
| `make deploy` | | |

## Who did what

| Agent | Did |
|---|---|
| | |

## Decisions
- Choices made, each with the alternative that was rejected and why.
- Proposed changes to DESIGN.md, if any (not applied without approval).

## Not verified
- Every gap, untested path or skipped check. "none" only if true.

## Next
- The next step, and anything it depends on.
