# herdr-collab

An agent skill for orchestrating **herdr** multi-workspace work from one lead
window: name panes, push messages between any agents, dispatch a ticket to a
worker, hand a finish package to an executor clerk, and bounce test failures
back to the worker.

Core principle: **push messages; never poll.** Whoever finishes a step pushes
the next peer — no `agent wait` loops, no file-watch monitors.

## What it does

- **Name panes** so they become addressable (sidebar labels are not addresses)
- **Talk** between any named panes (`tell` / `notify`), one `--to` or many
- **Dispatch** a self-contained brief to a worker (`/new` first, then the brief)
- **Hand off** a finish package (`handoff`) to a clerk that runs tests, commits
  the listed files, optionally closes the GitHub issue, and cleans job temps
- **Bounce failures** back to the worker with command, exit code, and log path —
  the clerk never diagnoses

## Repository layout

```
SKILL.md                  # the skill definition (front matter + playbook)
scripts/herdr_peer.py     # peer messaging: peers/name/tell/send/run/handoff/notify/status
scripts/herdr_finish.py   # clerk finish package: execute the handshake, never diagnose
```

## Requirements

- Python 3.10+ (`py` on Windows, `python3` elsewhere) — stdlib only, no deps
- The `herdr` binary: set `HERDR` / `HERDR_HOME`, put it on `PATH`, or rely on
  the built-in fallback path
- A git work tree per workspace; job files live in `{repo}/.herdr/jobs/`
  (override with `$HERDR_JOBS`)

## Install

Copy (or symlink) this directory into your agent's skills directory, e.g.
`~/.grok/skills/herdr-collab/`. Grok loads `SKILL.md` from there. The scripts
are invoked directly by their installed path — below, `<skill_dir>` stands for
wherever you installed the skill:

```
py <skill_dir>/scripts/herdr_peer.py <cmd>        # Windows
python3 <skill_dir>/scripts/herdr_peer.py <cmd>   # macOS/Linux
```

## Quick start

```
# who is around
py <skill_dir>/scripts/herdr_peer.py peers

# name a pane before talking to it
py <skill_dir>/scripts/herdr_peer.py name --pane w9:p1 --as sub-grok-2

# push a message to one or more peers
py <skill_dir>/scripts/herdr_peer.py tell \
  --from main-grok --to sub-grok-1 --to git-clerk --message "..."

# dispatch a ticket brief (worker: /new first, then this)
py <skill_dir>/scripts/herdr_peer.py send \
  --target sub-grok-1 --prompt-file brief.txt --job 12

# worker -> clerk handoff (clerk runs the finish package)
py <skill_dir>/scripts/herdr_peer.py handoff \
  --from sub-grok-1 --to git-clerk --job 12
```

Coding agents receive a prompt; bare shells get `.herdr/jobs/inbox-<name>.txt`.

## Roles (names are conventions)

| Role   | Typical name | Does | Does not |
| ------ | ------------ | ---- | -------- |
| Lead   | `main-grok`  | Brief, `/new`, verify success notifies | Run project tests, git, debug clerk failures |
| Worker | `sub-grok-N` | Edit files; run short local commands | git / close issues / wipe jobs; wait on clerk |
| Clerk  | `git-clerk`  | Run `finish_run`, commit listed files, optional issue close, delete listed job temps | Read tests, edit product code, invent steps |

## The handshake

The worker's last step writes `.herdr/jobs/<id>.done.json`:

```json
{
  "job": "12",
  "status": "pass",
  "from": "sub-grok-1",
  "lead": "main-grok",
  "clerk": "git-clerk",
  "on_pass": ["main-grok"],
  "on_fail": ["sub-grok-1"],
  "files": ["src/foo.ts"],
  "finish_run": ["npm test"],
  "commit_message": "feat: ...",
  "issue": 12,
  "issue_comment": "",
  "push": false,
  "temp_cleanup": [".herdr/jobs/brief-12.txt"]
}
```

Defaults: `on_fail=[from]`, `on_pass=[lead]`. The clerk runs
`herdr_finish.py --job <id>`, which executes `finish_run`, commits `files`
with `commit_message`, posts `issue_comment` + closes `issue` on GitHub when
set, deletes `temp_cleanup` (must stay under `.herdr/` or `temp/`), then
notifies `on_pass` — or `on_fail` on the first failing command, with the log
at `.herdr/jobs/<id>.run.json`.

## Hard rules

1. **Push, don't pull.** No wait loops, no file-watch monitors.
2. **Name before talk.** `peers` then `tell` / `notify` / `handoff`.
3. **`/new` then the brief.** Never paste `/new` and the ticket in one prompt.
4. **Short commands stay with the worker; once-per-ticket commands go in
   `finish_run`.**
5. **The clerk is an executor.** On failure it bounces the log to the worker
   and stops — it never diagnoses.
6. **The lead only wakes on `on_pass` or a human decision.** Never re-run a
   succeeded finish package.

See [SKILL.md](SKILL.md) for the full playbook the agent actually follows.
