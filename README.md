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
- **Cancel** a dispatched job before the clerk starts (`abort --job <id>`)

## Repository layout

```
SKILL.md                  # the skill definition — the playbook the agent actually follows
scripts/herdr_peer.py     # peer messaging: peers/name/tell/send/run/handoff/notify/status/abort
scripts/herdr_finish.py   # clerk finish package: execute the handshake, never diagnose
tests/test_units.py       # stdlib unittest for the pure/guard logic
LICENSE                   # MIT
```

## Requirements

- Python 3.10+ (`py` on Windows, `python3` elsewhere) — stdlib only, no deps
- The `herdr` binary: set `HERDR` / `HERDR_HOME`, or put it on `PATH`
- A git work tree per workspace; job files live in `{repo}/.herdr/jobs/`
  (override with `$HERDR_JOBS`)

## Install

Copy (or symlink) this directory into your agent's skills directory — wherever
the agent loads Markdown skills from, e.g. `~/.grok/skills/herdr-collab/`,
`~/.claude/skills/herdr-collab/`, or a project-level `.agents/skills/herdr-collab/`.
The scripts are invoked directly by their installed path — below, `<skill_dir>`
stands for wherever you installed the skill:

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

# cancel a dispatched job before the clerk starts
py <skill_dir>/scripts/herdr_peer.py abort --job 12
```

Coding agents receive a prompt; bare shells get `.herdr/jobs/inbox-<name>.txt`
(appended, timestamped).

## How a ticket flows

1. The lead names panes, writes a self-contained brief, sends `/new` then the brief.
2. The worker does the work, writes the handshake `.herdr/jobs/<id>.done.json`,
   and runs `handoff`.
3. The clerk executes the finish package: `finish_run` (per-command timeout,
   default 180s — long suites set `timeout_sec`), commits `files`, optionally
   comments + closes the GitHub issue, cleans `temp_cleanup`. On any failure it
   bounces the log (`.herdr/jobs/<id>.run.json`) to the worker and stops — it
   never diagnoses.
4. Success notifies the lead; the executed handshake and run log move to
   `.herdr/jobs/archive/`. Reruns are idempotent — an already-committed tree
   skips `git commit`, so retrying after a GitHub failure is safe.

## Tests

```
py -m unittest discover -s tests      # Windows
python3 -m unittest discover -s tests # macOS/Linux
```

## Full playbook

The roles table, the handshake schema, and the hard rules live in
[SKILL.md](SKILL.md) — that is the file the agent follows.
