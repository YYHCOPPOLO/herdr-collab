---
name: herdr-collab
description: >
  Orchestrate herdr multi-workspace work: name panes, push messages between any
  agents, dispatch a ticket to a worker, hand a finish package to an executor
  clerk, bounce test failures back to the worker. Use when the user mentions
  herdr, git-clerk, sub-grok, main-grok, handoff, 多窗口, 派工, 收工包, or runs
  /herdr-collab — and whenever herdr is running with multiple panes and a task
  could be delegated to a worker: dispatch it, do not do it yourself.
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

Any **named** pane can talk to any other. Names live in herdr's agent registry and expire when the agent exits; a bare shell has no name — address it by pane id (`wN:pM`). New agent pane: `herdr_peer.py spawn --name sub-grok-2 --kind grok` (splits a pane and starts the agent, all herdr-native); to adopt an existing agent pane instead: `herdr_peer.py name --pane w9:p1 --as sub-grok-2`.

## Hard rules

1. **Push, don't pull.** No `herdr agent wait` loops. No file-watch monitors. Who finishes pushes the next peer.
2. **Name before talk.** Sidebar labels are not addresses. `peers` then `tell`/`notify`/`handoff`.
3. **`/new` then the brief.** Never paste `/new` and the ticket in one prompt.
4. **Short commands stay with the worker** (compile, one test). **Once-per-ticket commands go in `finish_run`** (full suite, e2e, launch app).
5. **Clerk is an executor.** `finish_run` failure → notify `from` / `on_fail` (the worker) with command, exit code, and `.herdr/jobs/<job>.run.json`. Stop. Do not diagnose.
6. Lead only wakes on `on_pass` or a human decision. Do not re-run the finish package after a success notify.
7. **Escalation is not retry.** Past `max_bounces` the lead joins the blocked notify. The clerk never re-runs a failed command unchanged.

## Talk

```
py <skill_dir>/scripts/herdr_peer.py peers
py <skill_dir>/scripts/herdr_peer.py spawn --name sub-grok-2 --kind grok
py <skill_dir>/scripts/herdr_peer.py init --job 12 --from sub-grok-1
py <skill_dir>/scripts/herdr_peer.py tell --from main-grok --to sub-grok-1 --to git-clerk --message "..."
py <skill_dir>/scripts/herdr_peer.py notify --from git-clerk --to sub-grok-1 --job 12 --phase blocked --message "exit 1, see .herdr/jobs/12.run.json"
```

`--to` repeats. Coding agents get a prompt; bare shells get `.herdr/jobs/inbox-<name>.txt` (appended, timestamped — earlier messages are kept; for pane-id targets `:` becomes `_`, e.g. `inbox-w2_p1.txt`).

## Dispatch a ticket

1. `peers` — the full pane view (agents **and** bare shells, with workspace labels). Agent names expire when the agent exits; workspace labels persist, so after any restart re-`name` workers/clerk by their labels. Rename this lead pane if needed: `name --pane <lead-pane> --as main-grok`.
2. Write a **self-contained** brief (worker has no lead history): scope, do-not, spec (inline or by reference), files they may touch, handshake path, `handoff` command.
3. `tell`/`send` only `/new` to the worker. When idle, `send --target <worker> --prompt-file <brief> --job <id>`.
4. Stop. Do not watch them.

Brief skeleton (copy and fill):

```
# Job <id>: <one-line goal>
Scope: <files/dirs the worker may touch>
Do not: <out-of-scope actions>
Spec: <path/URL/#id — or "this brief is the spec">
Done when: <observable acceptance>
Skills: <skills the worker should invoke, if any>
finish_run: [<once-per-ticket commands>]
commit_message: <message>
```

Where the spec comes from — the skill is workflow-agnostic, it only requires the result to be self-contained:

- **The project has tickets/specs** (issues, plan docs): reference them by path/URL. Never paste contents.
- **No ticket workflow**: the brief itself carries the distilled spec — goal, constraints, acceptance. Self-contained means exactly that.
- **Continuation dispatch** (hand over half-done exploration/debugging): if the host agent has a handoff/compaction skill, use it to write a continuation doc, then reference its path under `Spec`. An authoring aid, never a dependency.

Either way: reference artifacts by path, redact secrets.

Worker last steps: write `.herdr/jobs/<id>.done.json` (`init --job <id>` scaffolds it; `handoff` validates it before the clerk is involved), then

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
  "max_bounces": 3,
  "env": {"CI": "1"},
  "commit_message": "feat: ...",
  "issue": 12,
  "issue_comment": "",
  "push": false,
  "temp_cleanup": [".herdr/jobs/brief-12.txt"]
}
```

Defaults: `on_fail=[from]`, `on_pass=[lead]`, `timeout_sec=180` per `finish_run` command — long suites must set it explicitly. String commands split with POSIX quoting rules (`shlex`); use the array form for paths or tricky args; an entry may also be an object `{"cmd": ..., "soft": true, "timeout_sec": 300, "env": {...}}` — `soft` failures are logged and never stop the run, and the success notify reports their count. `env` is merged over the clerk's environment for `finish_run` only. A failure bounces to `on_fail`; past `max_bounces` (default 3) the blocked notify also goes to `on_pass`. Reruns are idempotent: an already-committed tree skips `git commit`, so retrying after a GitHub failure is safe. Clerk runs `herdr_finish.py` (same `scripts/`); inside herdr it reports running/blocked/done to its pane's sidebar. `temp_cleanup` must stay under the repo (prefer `.herdr/` or project `temp/`). Executed handshakes and run logs move to `.herdr/jobs/archive/`.

## Cancel a job

`herdr_peer.py abort --job <id>` writes the `.herdr/jobs/<id>.abort` sentinel. The clerk checks it before starting: if present, nothing runs, the handshake is dropped, and `on_pass` gets an `other` notify.

## Chain tickets

A dependency "B after A" is a message chain, not a queue: A's `on_pass` is the lead; when the success notify arrives, the lead dispatches B (`/new`, then `send`). No scheduler — the lead decides whether B still makes sense given A's outcome.

## More than one clerk

Any named pane can be a clerk: spawn or rename another one (`git-clerk-2`) and `handoff --to git-clerk-2`. Job files are keyed by job id, so parallel clerks do not collide.

## On a notify to this lead

- **`blocked` from clerk:** do not debug. Confirm the worker was the `on_fail` target; if the notify landed here by mistake, `tell` the worker the log path only.
- **`git` / success:** verify commit/issue from the message. Do not re-test, do not re-commit.
- **`blocked` from a worker:** answer only the decision they asked.

## Clerk occupant

If `git-clerk` is a shell, `handoff` pane-runs `herdr_finish.py`. If it is an agent (grok/omp/…), `handoff` prompts it to run that same command in the foreground and stop on failure.
