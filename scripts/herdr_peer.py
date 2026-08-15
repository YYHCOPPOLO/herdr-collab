#!/usr/bin/env python3
"""Peer messaging for any named herdr workspace. Push only."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LEAD = "main-grok"
DEFAULT_CLERK = "git-clerk"


def repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else Path.cwd()


def jobs_dir() -> Path:
    env = os.environ.get("HERDR_JOBS")
    path = Path(env) if env else repo_root() / ".herdr" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def handshake_path(job: str) -> Path:
    return jobs_dir() / f"{job}.done.json"


def herdr_bin() -> Path:
    for candidate in (
        os.environ.get("HERDR"),
        str(Path(os.environ["HERDR_HOME"]) / "bin" / "herdr.exe") if os.environ.get("HERDR_HOME") else None,
        str(Path(os.environ["HERDR_HOME"]) / "herdr") if os.environ.get("HERDR_HOME") else None,
        shutil.which("herdr"),
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit("herdr not found. Set HERDR or HERDR_HOME, or put herdr on PATH.")


def herdr(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(herdr_bin()), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def herdr_json(args: list[str]) -> dict:
    proc = herdr(args)
    raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw}
    if proc.returncode != 0:
        raise SystemExit(f"herdr {' '.join(args)} failed ({proc.returncode}): {payload.get('error', raw)}")
    return payload if isinstance(payload, dict) else {"result": payload}


def resolve_target(target: str, pane: str | None) -> str:
    got = herdr(["agent", "get", target])
    if got.returncode == 0:
        return target
    if not pane:
        raise SystemExit(f"agent '{target}' not found. Run: herdr_peer.py name --pane wN:p1 --as {target}")
    herdr_json(["agent", "rename", pane, target])
    return target


def agent_record(target: str) -> dict:
    result = herdr_json(["agent", "get", target]).get("result") or {}
    agent = result.get("agent") if isinstance(result.get("agent"), dict) else result
    return agent or {}


def record_is_coding(record: dict) -> bool:
    # herdr fills the agent field when it detects a coding agent in the pane;
    # bare shells have no agent field at all.
    return bool(record.get("agent"))


def occupant_kind(target: str) -> str:
    return str(agent_record(target).get("agent") or "").lower()


def is_coding_agent(target: str) -> bool:
    return record_is_coding(agent_record(target))


def pane_id_of(target: str) -> str:
    pane = agent_record(target).get("pane_id")
    if not pane:
        raise SystemExit(f"no pane_id for {target}")
    return pane


def deliver(target: str, text: str) -> dict:
    if is_coding_agent(target):
        return herdr_json(["agent", "prompt", target, text])
    inbox = jobs_dir() / f"inbox-{target}.txt"
    stamp = datetime.now().isoformat(timespec="seconds")
    with inbox.open("a", encoding="utf-8") as fh:
        fh.write(f"=== {stamp} ===\n{text}\n\n")
    return {"type": "inbox", "path": str(inbox), "kind": occupant_kind(target)}


def listed_agents() -> list[dict]:
    result = herdr_json(["agent", "list"]).get("result") or {}
    return list(result.get("agents") or [])


def display_name(rec: dict) -> str:
    return rec.get("name") or rec.get("pane_id") or "?"


def py_cmd() -> str:
    return "py" if os.name == "nt" else "python3"


def finish_cmd(job: str, worker: str) -> str:
    script = SKILL_DIR / "scripts" / "herdr_finish.py"
    return f"{py_cmd()} {script} --job {job} --worker {worker}"


def cmd_peers(_args: argparse.Namespace) -> int:
    print("name\tkind\tpane\tstatus")
    for rec in listed_agents():
        print("\t".join([
            display_name(rec),
            str(rec.get("agent") or ""),
            str(rec.get("pane_id") or ""),
            str(rec.get("agent_status") or ""),
        ]))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    print(json.dumps({
        "workspaces": herdr_json(["workspace", "list"]).get("result"),
        "agents": herdr_json(["agent", "list"]).get("result"),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_name(args: argparse.Namespace) -> int:
    herdr_json(["agent", "rename", args.pane, args.as_name])
    print(json.dumps({"name": args.as_name, "pane": args.pane}, ensure_ascii=False))
    return 0


def cmd_tell(args: argparse.Namespace) -> int:
    text = args.message or ""
    if args.prompt_file:
        file_text = Path(args.prompt_file).read_text(encoding="utf-8")
        text = f"{text}\n{file_text}".strip() if text else file_text
    if not text:
        raise SystemExit("tell needs --message and/or --prompt-file")
    header = f"【来自 {args.source}】"
    if args.job:
        header += f" #{args.job}"
    body = f"{header}\n{text}"
    delivered = []
    for raw in args.to:
        target = resolve_target(raw, args.pane)
        delivered.append({"to": target, "result": deliver(target, body)})
    print(json.dumps({"from": args.source, "delivered": delivered}, ensure_ascii=False, indent=2))
    return 0


def append_handshake(prompt: str, job: str) -> str:
    path = handshake_path(job).as_posix().replace("\\", "/")
    extra = (
        f"\n\n---\nWrite `{path}`. Include from/lead/clerk/on_pass/on_fail/files/"
        f"finish_run/commit_message. Then:\n"
        f"{py_cmd()} {SKILL_DIR / 'scripts' / 'herdr_peer.py'} handoff "
        f"--from <your-name> --to git-clerk --job {job}\n"
        "Do not git. Do not monitor. Talk with tell/notify to any named peer.\n"
    )
    if path in prompt:
        return prompt
    return prompt.rstrip() + extra


def cmd_send(args: argparse.Namespace) -> int:
    text = Path(args.prompt_file).read_text(encoding="utf-8")
    if args.job:
        text = append_handshake(text, args.job)
    target = resolve_target(args.target, args.pane)
    result = deliver(target, text)
    print(json.dumps({
        "target": target,
        "job": args.job,
        "handshake": str(handshake_path(args.job)) if args.job else None,
        "result": result.get("result", result),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    target = resolve_target(args.target, args.pane)
    command = " ".join(args.command)
    result = herdr_json(["pane", "run", pane_id_of(target), command])
    print(json.dumps({
        "target": target, "command": command, "result": result.get("result", result),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    done = handshake_path(args.job)
    if not done.is_file():
        raise SystemExit(f"missing handshake {done}")
    clerk = resolve_target(args.to, args.pane)
    cmd = finish_cmd(args.job, args.source)
    if is_coding_agent(clerk):
        text = (
            f"【交接】{args.source} → {clerk} · #{args.job}\n"
            f"Handshake `{done.as_posix()}`.\nRun in the foreground, do not background:\n`{cmd}`\n"
            "On finish_run failure: notify from/on_fail (the worker) with the log. "
            "Do not diagnose, do not edit product code. On success: notify on_pass."
        )
        result = deliver(clerk, text)
    else:
        result = herdr_json(["pane", "run", pane_id_of(clerk), cmd])
    print(json.dumps({
        "from": args.source, "to": clerk, "job": args.job,
        "result": result.get("result", result),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    lines = [f"【通知】{args.source}"]
    if args.job:
        lines[0] += f" · #{args.job}"
    if args.phase:
        lines[0] += f" · {args.phase}"
    if args.phase == "blocked":
        lines.append("卡住了。执行者不要查。只把日志交给干活的工人。")
    elif args.phase == "git":
        lines.append("收工包做完。核对即可，不要重做，不要盯窗口。")
    if args.message:
        lines.append(args.message)
    text = "\n".join(lines)
    delivered = []
    for raw in args.to:
        target = resolve_target(raw, args.pane)
        delivered.append({"to": target, "result": deliver(target, text)})
    print(json.dumps({
        "from": args.source, "job": args.job, "phase": args.phase, "delivered": delivered,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = {"agent": herdr_json(["agent", "get", args.target]).get("result")}
    if args.job:
        done = handshake_path(args.job)
        payload["handshake"] = str(done)
        payload["handshake_exists"] = done.is_file()
        if done.is_file():
            payload["handshake_body"] = json.loads(done.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_abort(args: argparse.Namespace) -> int:
    sentinel = jobs_dir() / f"{args.job}.abort"
    sentinel.write_text("abort\n", encoding="utf-8")
    print(json.dumps({
        "job": args.job, "abort": str(sentinel),
        "note": "clerk checks this before starting; aborted jobs notify on_pass and do not run",
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="herdr peer messaging")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("peers")
    name = sub.add_parser("name")
    name.add_argument("--pane", required=True)
    name.add_argument("--as", dest="as_name", required=True)
    tell = sub.add_parser("tell")
    tell.add_argument("--from", dest="source", required=True)
    tell.add_argument("--to", action="append", required=True)
    tell.add_argument("--message", default="")
    tell.add_argument("--prompt-file")
    tell.add_argument("--job")
    tell.add_argument("--pane")
    send = sub.add_parser("send")
    send.add_argument("--target", required=True)
    send.add_argument("--prompt-file", required=True)
    send.add_argument("--pane")
    send.add_argument("--job")
    run = sub.add_parser("run")
    run.add_argument("--target", required=True)
    run.add_argument("--pane")
    run.add_argument("command", nargs=argparse.REMAINDER)
    handoff = sub.add_parser("handoff")
    handoff.add_argument("--from", dest="source", required=True)
    handoff.add_argument("--to", default=DEFAULT_CLERK)
    handoff.add_argument("--job", required=True)
    handoff.add_argument("--pane")
    notify = sub.add_parser("notify")
    notify.add_argument("--from", dest="source", required=True)
    notify.add_argument("--to", action="append", required=True)
    notify.add_argument("--job", default="")
    notify.add_argument("--phase", default="other", choices=("done", "git", "blocked", "other"))
    notify.add_argument("--pane")
    notify.add_argument("--message", default="")
    status = sub.add_parser("status")
    status.add_argument("--target", required=True)
    status.add_argument("--job")
    abort = sub.add_parser("abort")
    abort.add_argument("--job", required=True)
    args = parser.parse_args()
    fn = {
        "list": cmd_list, "peers": cmd_peers, "name": cmd_name, "tell": cmd_tell,
        "send": cmd_send, "run": cmd_run, "handoff": cmd_handoff,
        "notify": cmd_notify, "status": cmd_status, "abort": cmd_abort,
    }[args.cmd]
    if args.cmd == "run":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        if not args.command:
            raise SystemExit("run needs a command after --")
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
