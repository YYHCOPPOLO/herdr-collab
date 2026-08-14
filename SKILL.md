---
name: herdr-collab
description: >
  Orchestrate herdr multi-workspace work: name panes, push messages between any
  agents, dispatch a ticket to a worker, hand a finish package to an executor
  clerk, bounce test failures back to the worker. Use when the user mentions
  herdr, git-clerk, sub-grok, main-grok, handoff, 多窗口, 派工, 收工包, or runs
  /herdr-collab.
---

# herdr-collab

Lead from this window. Other herdr panes do the work. **Push messages; never poll.**

Scripts live next to this file. Substitute the skill's install directory for `<skill_dir>`:

```
py <skill_dir>/scripts/herdr_peer.py <cmd>        # Windows
python3 <skill_dir>/scripts/herdr_peer.py <cmd>   # macOS/Linux
```

The herdr binary is resolved from `$HERDR`, `$HERDR_HOME`, or PATH. Job files: `{repo}/.herdr/jobs/` (or `$HERDR_JOBS`).

## Roles (names are conventions)

| Role | Typical name | Does | Does not |
| --- | --- | --- | --- |
| Lead | `main-grok` | Brief, `/new`, verify success notifies | Run project tests, git, debug clerk failures |
| Worker | `sub-grok-N` | Edit files; run short local commands | git / close issues / wipe jobs; wait on clerk |
| Clerk | `git-clerk` | Run `finish_run`, commit listed files, optional issue close, delete listed job temps | Read tests, edit product code, retry "to see", invent steps |

Any **named** pane can talk to any other. New pane: `herdr_peer.py name --pane w9:p1 --as sub-grok-2`.

## Hard rules

1. **Push, don't pull.** No `herdr agent wait` loops. No file-watch monitors. Who finishes pushes the next peer.
2. **Name before talk.** Sidebar labels are not addresses. `peers` then `tell`/`notify`/`handoff`.
3. **`/new` then the brief.** Never paste `/new` and the ticket in one prompt.
4. **Short commands stay with the worker** (compile, one test). **Once-per-ticket commands go in `finish_run`** (full suite, e2e, launch app).
5. **Clerk is an executor.** `finish_run` failure → notify `from` / `on_fail` (the worker) with command, exit code, and `.herdr/jobs/<job>.run.json`. Stop. Do not diagnose.
6. Lead only wakes on `on_pass` or a human decision. Do not re-run the finish package after a success notify.

## Talk

```
py <skill_dir>/scripts/herdr_peer.py peers
py <skill_dir>/scripts/herdr_peer.py tell --from main-grok --to sub-grok-1 --to git-clerk --message "..."
py <skill_dir>/scripts/herdr_peer.py notify --from git-clerk --to sub-grok-1 --job 12 --phase blocked --message "exit 1, see .herdr/jobs/12.run.json"
```

`--to` repeats. Coding agents get a prompt; bare shells get `.herdr/jobs/inbox-<name>.txt` (appended, timestamped — earlier messages are kept).

## Dispatch a ticket

1. `peers`. Rename this lead pane if needed: `name --pane <lead-pane> --as main-grok`.
2. Write a **self-contained** brief (worker has no lead history): scope, do-not, spec/issue, files they may touch, handshake path, `handoff` command.
3. `tell`/`send` only `/new` to the worker. When idle, `send --target <worker> --prompt-file <brief> --job <id>`.
4. Stop. Do not watch them.

Brief skeleton (copy and fill):

```
# Job <id>: <one-line goal>
Scope: <files/dirs the worker may touch>
Do not: <out-of-scope actions>
Spec/issue: <link or #id>
Done when: <observable acceptance>
finish_run: [<once-per-ticket commands>]
commit_message: <message>
```

Worker last steps: write `.herdr/jobs/<id>.done.json`, then

```
py <skill_dir>/scripts/herdr_peer.py handoff --from <worker> --to git-clerk --job <id>
```

## Handshake

`.herdr/jobs/<id>.done.json`:

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
  "timeout_sec": 180,
  "env": {"CI": "1"},
  "commit_message": "feat: ...",
  "issue": 12,
  "issue_comment": "",
  "push": false,
  "temp_cleanup": [".herdr/jobs/brief-12.txt"]
}
```

Defaults: `on_fail=[from]`, `on_pass=[lead]`, `timeout_sec=180` per `finish_run` command — long suites must set it explicitly. String commands split with POSIX quoting rules (`shlex`); use the array form for paths or tricky args. `env` is merged over the clerk's environment for `finish_run` only. Reruns are idempotent: an already-committed tree skips `git commit`, so retrying after a GitHub failure is safe. Clerk runs `herdr_finish.py` (same `scripts/`). `temp_cleanup` must stay under the repo (prefer `.herdr/` or project `temp/`). Executed handshakes and run logs move to `.herdr/jobs/archive/`.

## Cancel a job

`herdr_peer.py abort --job <id>` writes the `.herdr/jobs/<id>.abort` sentinel. The clerk checks it before starting: if present, nothing runs, the handshake is dropped, and `on_pass` gets an `other` notify.

## On a notify to this lead

- **`blocked` from clerk:** do not debug. Confirm the worker was the `on_fail` target; if the notify landed here by mistake, `tell` the worker the log path only.
- **`git` / success:** verify commit/issue from the message. Do not re-test, do not re-commit.
- **`blocked` from a worker:** answer only the decision they asked.

## Clerk occupant

If `git-clerk` is a shell, `handoff` pane-runs `herdr_finish.py`. If it is an agent (grok/omp/…), `handoff` prompts it to run that same command in the foreground and stop on failure.
