# Ecoscribe: instructions for every Claude session (Windows and Mac)

Ecoscribe is one codebase for Windows and macOS. Two Claude sessions work on it: one on Windows
(merges and runs the Windows desktop/GPU tests), one on the Mac. Erik isn't a programmer: he gets
outcomes in plain words and only real choices (money, publishing, his desktop, what the app does).

## How we work: STANDARD PROCESS (enforced, not optional)

1. **One ticket = one branch = one pull request.** Branch from the *latest* `origin/main`
   (`git fetch && git switch -c <short-name> origin/main`). Name the ticket in commits:
   `(ticket: dictado-xxx)`.
2. **Never stack.** Never branch from another open branch. A follow-up waits until the first PR
   is merged, then starts from the updated main. The `pr-shape` check fails stacked PRs.
3. **Open the PR as soon as the branch is pushed** (`gh pr create --base main`), even if small.
4. **Merge only when green:** `unit (windows-latest)`, `unit (macos-14)` and `pr-shape` must pass
   (GitHub enforces it on `main`, for everyone). The Windows session also runs the local desktop
   and GPU suites when a PR touches shared code. Merge commits, no squash.
5. **Short-lived branches:** merge within the day; branches are deleted on merge. If main moves,
   rebase your one branch, never a pile.
6. **Nothing goes straight to main**, ticket/beads updates included: they ride in the PR.
7. **Public repo:** before every push, `tests/test_no_secrets.py`, `tests/test_repo_hygiene.py` and
   `tests/test_no_personal_data.py` pass and the diff has no names, personal paths, keys or calendar links.
   **Never any of Erik's personal data** anywhere in git, tickets (`.beads/issues.jsonl` is public),
   commit messages, PR bodies or comments: no dictation or meeting text, no quotes of what he says,
   no numbers about his speech or usage. Tests and demo data use invented text; describe requests
   neutrally ("the user wants X").
8. **Parity:** OS-specific work updates `ecoscribe/platform/base.py` + `FEATURES.md` in the same PR
   (`tests/test_platform_contract.py` checks it); the other platform gets done, a ticket, or
   "not needed" with a reason.
9. **gh account:** the repo belongs to ErikBros. Use `GH_TOKEN=$(gh auth token --user ErikBros) gh ...`
   per command; never leave `gh auth switch` on the personal account (other sessions are work).

## Build & test

```bash
. tools/winpy.sh                                   # Windows (from WSL): WINPY + APP_W
wtest "$APP_W\\tests" -q -m "not gpu and not win"   # unit
wtest "$APP_W\\tests" -q -m gpu                     # GPU (NVIDIA)
wtest "$APP_W\\tests" -q -m win                     # real desktop, waits for 45 s idle
npm install && npm run smoke                       # the window's JavaScript (jsdom)
wpy "$APP_W\\tools\\build.py" --installer          # Windows installer
python tools/build_mac.py                          # macOS .app + .dmg (on the Mac)
tools/mac_check.sh                                 # macOS test suite (on the Mac)
```


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH YOUR BRANCH AND OPEN/UPDATE ITS PR** (see STANDARD PROCESS above; main is protected):
   ```bash
   git fetch && git rebase origin/main   # your one branch only
   git push -u origin HEAD
   gh pr create --base main              # if it has no PR yet
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
