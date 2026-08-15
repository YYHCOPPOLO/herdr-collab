# herdr-collab Context

Orchestration conventions for herdr multi-workspace work: a lead pane dispatches
self-contained tickets to worker panes, and an executor clerk pane runs each
finish package without ever diagnosing failures. The only communication style
is push.

## Language

**Lead**:
The pane that writes the brief, dispatches the ticket, and only verifies success notifies. Convention name: `main-grok`. 别名：指挥。

**Worker**:
The pane that edits files, runs short local commands, and writes the handshake when done. Convention name: `sub-grok-N`. 别名：工人。

**Clerk**:
The executor pane that runs a finish package exactly as written and stops on the first failure. Convention name: `git-clerk`. 别名：执行。_Avoid_: auto-fixer, reviewer.

**Peer**:
Any addressable pane in the herdr instance. Agent panes are addressed by name (names expire when the agent exits); bare shells are addressed by pane id (`wN:pM`). Sidebar labels are not addresses.

**Spawn**:
Opening a new peer from the lead: `pane split` + `agent start` (or a bare shell) under a given name, all herdr-native. The opposite move is `name`, adopting an existing pane.

**Job**:
One ticket's unit of orchestration, keyed by a job id. All its files live under `.herdr/jobs/`.

**Brief**:
The self-contained dispatch text a worker receives — scope, do-not, spec, acceptance, handshake instructions. The worker has no lead history. 别名：任务书。

**Handshake**:
The `.herdr/jobs/<id>.done.json` a worker writes to declare the work done and describe the finish package. 别名：回执。

**Finish package**:
The clerk-side execution of a handshake: `finish_run`, commit, optional issue close, temp cleanup, notify. 别名：收工包。

**Bounce**:
The clerk's only failure move: notify `on_fail` with command, exit code, and log path, then stop. Never diagnose. 别名：退回。

**Escalation**:
After `max_bounces` (default 3) bounces of the same job, the lead is added to the failure notify — a human should step in. 升级。_Avoid_: blind retry（盲重试，clerk 原样重跑，明确否决）.

**Soft command**:
A `finish_run` entry marked `"soft": true`: its failure (non-zero exit or timeout) is logged and reported in the success notify, but never stops the run.

**Abort sentinel**:
A `.herdr/jobs/<id>.abort` file that cancels a job before the clerk starts it. 取消哨兵。

**Archive**:
`.herdr/jobs/archive/` — where executed handshakes and run logs are moved for audit. 归档。

**Inbox**:
`.herdr/jobs/inbox-<name>.txt` — the appended, timestamped message file for a pane occupied by a bare shell.

**Push, don't pull**:
The core principle: whoever finishes a step pushes the next peer. No wait loops, no file-watch monitors. 只推不拉。_Avoid_: polling, monitor, `agent wait` loops.
