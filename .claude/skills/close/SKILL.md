---
name: close
description: End an Ecoscribe session (Windows or Mac) with nothing stranded - every change in a merged or open PR, privacy gates run, tickets and the release current, the other platform's session told, and a paste-ready prompt for the next session. Triggered by `/close`, "close the session", "close session", "wrap up".
user-invocable: true
trigger: "/close"
---

# /close: Ecoscribe session close

Ecoscribe is a **public** repo worked on by two sessions (Windows and Mac) under the standard process in
`CLAUDE.md`: one ticket = one branch from `origin/main` = one PR, main protected, nothing straight to main.
So unlike the workspace's local-only `/close`, this one **pushes, through PRs**. Erik isn't a programmer:
he reads only the last block. Keep the close to bookkeeping, about 5 minutes; anything bigger becomes a ticket.

Every `gh` call: `GH_TOKEN=$(gh auth token --user ErikBros) gh ...` (never `gh auth switch`).
Progress bar: `python3 ~/.claude-personal/statusline/taskbar.py set "close" 0 8`, `step` per step, `clear` at the end.

## 1. Health check (read-only)

```bash
git fetch --prune && git status -sb && git branch -vv && git stash list
GH_TOKEN=$(gh auth token --user ErikBros) gh pr list --author @me --json number,title,headRefName,mergeable
bd list --status=in_progress ; bd ready
```

List: uncommitted files, local branches, stashes, open PRs and their checks, tickets in progress.

## 2. Nothing stranded

- **Every change is on a pushed branch with a PR.** Uncommitted code belongs to its ticket's branch;
  a commit on local `main` is a mistake: move it to a branch.
- **Open PRs:** all three checks green (`unit (windows-latest)`, `unit (macos-14)`, `pr-shape`) -> merge
  (`--merge --delete-branch`). Red -> fix it if it's small, else leave it open and say why. No checks at
  all -> check githubstatus.com; GitHub dropping events is not ours to fix, say so.
- **Two PRs touching `.beads/`** conflict on merge: merge one, then rebase the next and rebuild
  `.beads/issues.jsonl` from main's file plus that ticket's line from `bd export` (never hand-edit
  other tickets' lines). `interactions.jsonl` is append-only: main's lines plus the branch's new ones.
- **Ticket changes made after the last PR** (closes, notes, new tickets) ride in a PR too: branch
  `beads-session-close` from `origin/main`, commit `.beads/`, PR, merge when green (as #38 did).
- Afterwards: merged branches deleted locally, no stashes, local `main` == `origin/main`.

## 3. Privacy gates (before every push in this close)

```bash
. tools/winpy.sh && wtest "$APP_W\\tests\\test_no_personal_data.py" "$APP_W\\tests\\test_no_secrets.py" "$APP_W\\tests\\test_repo_hygiene.py" -q -rs
# Mac: tools/mac_check.sh runs them (and test_no_personal_data against the real history)
```

Must be **6 passed, 0 skipped**: a skip means the gate didn't run. Then reread what this session wrote:
commit messages, PR bodies, ticket text, messages to the other session. **No dictation or meeting text,
no quotes of what Erik says, no numbers about his speech or usage, no names, no personal paths.**
Tests and demo data use invented text. Describe requests neutrally ("the user wants X").

## 4. Version and release

If this session installed a build on Erik's computer: `ecoscribe/__init__.py` on main has that version,
and GitHub has release `vX.Y.Z` (marked latest, notes on what's new) with the installer:
`Ecoscribe-Setup-X.Y.Z.exe` from Windows, `Ecoscribe-X.Y.Z.dmg` from the Mac. Never install over a live
meeting or file job: check for `--meeting` / `--transcribe` / `--speakers` processes first.

## 5. Tickets

- Finished -> `bd close <id> --reason="what was done and how it was checked"` (neutral words).
- Started, not finished -> notes on where it stands, keep it in progress or put it back to open.
- Anything found and not done -> a ticket now (P0-P4), with the evidence, so nothing lives only in chat.
- OS-specific work: the other platform has code, a ticket, or "not needed" in `ecoscribe/platform/base.py`
  and `FEATURES.md` (`tests/test_platform_contract.py`).

## 6. Tell the other session

`ListAgents`, then `SendMessage` to the other platform's session (the Mac one is usually "NEXT-SESSION
prompt"; Remote Control delivery is queued while it's offline). One message, specific:
what merged in shared code, which tickets are theirs and in what order, what to wait for,
anything that changed their numbers (speed, tests). Answer its open questions with a decision.

## 7. Three questions

Ask Erik exactly, in one line each:
1. "Did I get anything wrong today?"
2. "Anything I should remember for next time?"
3. "Any rule to add or change?"

Each real answer becomes a `bd remember` (project knowledge; CLAUDE.md: not MEMORY.md) or a rule in
`CLAUDE.md` through a PR. Show the text first. Same privacy rule: no personal data.

## 8. Next-session prompt + the last block

Write `.claude/next-session.md` (gitignored, never committed) as a **paste-ready prompt** for the next
session on this platform, in the shape Erik uses:

```
Ecoscribe (ErikBros/ecoscribe), <Windows|Mac> session. Read CLAUDE.md first: <process one-liner>.
HARD RULE: <privacy one-liner>. Read `bd memories` too.
State: <installed version, release, main sha, open PRs and why>.
Work, in order: <numbered, ticket ids, one line each>.
Waiting on Erik (don't do): <ticket ids>.
```

Then end the session with one short block, plain words, for Erik:
1. **Shipped:** what he can now do or what changed, versions installed and released
2. **Open:** PRs or tickets still running, and why (one line each)
3. **Waiting on you:** decisions or checks only he can do
4. **Next session:** "paste `.claude/next-session.md`" and the prompt itself
plus the three questions from step 7.

## Anti-patterns

- Ending with work only on a local branch, or "ready to push when you are". Push it, open the PR.
- Committing to main, stacking a branch on another open branch, squash merges.
- A privacy gate that skipped and was counted as passed.
- Installing over a live meeting; a release without the installer attached.
- A long retrospective. Erik reads the last block; the details live in PRs and tickets.
