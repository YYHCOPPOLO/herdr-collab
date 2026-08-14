#!/usr/bin/env python3
"""Clerk finish package: execute the handshake, never diagnose failures."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

PEER = Path(__file__).resolve().with_name("herdr_peer.py")


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


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(repo_root()),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def notify_many(source: str, job: str, phase: str, targets: list[str], message: str) -> None:
    py = "py" if os.name == "nt" else "python3"
    seen: list[str] = []
    for to in targets:
        if not to or to in seen:
            continue
        seen.append(to)
        cmd = [py, str(PEER), "notify", "--from", source, "--to", to, "--job", job, "--phase", phase, "--message", message]
        proc = run(cmd)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)


def github_repo() -> str | None:
    proc = run(["git", "remote", "get-url", "origin"])
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def gh_token() -> str:
    filled = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n",
        capture_output=True, text=True, cwd=str(repo_root()),
    )
    return next(l.split("=", 1)[1] for l in filled.stdout.splitlines() if l.startswith("password="))


def gh_api(method: str, path: str, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    last = None
    for _ in range(4):
        try:
            req = urllib.request.Request(
                "https://api.github.com" + path, data=data, method=method,
                headers={
                    "Authorization": f"Bearer {gh_token()}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            return json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last


def safe_cleanup(rel: str) -> Path:
    root = repo_root().resolve()
    path = (root / rel).resolve()
    if root not in path.parents and path != root:
        raise SystemExit(f"temp_cleanup outside repo: {rel}")
    herdr = (root / ".herdr").resolve()
    tmp = (root / "temp").resolve()
    if herdr not in path.parents and tmp not in path.parents and path not in (herdr, tmp):
        raise SystemExit(f"temp_cleanup must stay under .herdr/ or temp/: {rel}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--worker", default="")
    parser.add_argument("--clerk", default="git-clerk")
    args = parser.parse_args()
    job = args.job
    handshake = jobs_dir() / f"{job}.done.json"
    clerk = args.clerk
    if not handshake.is_file():
        notify_many(clerk, job, "blocked", ["main-grok"], f"missing {handshake}")
        return 1
    data = json.loads(handshake.read_text(encoding="utf-8"))
    worker = data.get("from") or args.worker or "sub-grok-1"
    lead = data.get("lead") or "main-grok"
    clerk = data.get("clerk") or clerk
    on_fail = list(data.get("on_fail") or [worker])
    on_pass = list(data.get("on_pass") or [lead])

    if str(data.get("status") or "").lower() not in ("pass", "ok", ""):
        notify_many(clerk, job, "blocked", on_fail, f"handshake status={data.get('status')}; not starting")
        return 1

    run_log = []
    for command in data.get("finish_run") or []:
        argv = command if isinstance(command, list) else command.split()
        proc = run(argv)
        run_log.append({"command": command, "exit": proc.returncode})
        if proc.returncode != 0:
            log = jobs_dir() / f"{job}.run.json"
            log.write_text(json.dumps({
                "job": job, "ok": False, "runs": run_log,
                "stdout": (proc.stdout or "")[-4000:],
                "stderr": (proc.stderr or "")[-4000:],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            notify_many(clerk, job, "blocked", on_fail, (
                f"执行失败，原样退回（clerk 不查、不改代码）。"
                f"命令：{command} exit={proc.returncode}。日志：{log.as_posix()}。"
                "修好后更新回执再 handoff。"
            ))
            return proc.returncode

    (jobs_dir() / f"{job}.run.json").write_text(
        json.dumps({"job": job, "ok": True, "runs": run_log}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    files = [f for f in (data.get("files") or []) if f]
    commit = ""
    if files and data.get("commit_message"):
        add = run(["git", "add", "--", *files])
        if add.returncode != 0:
            notify_many(clerk, job, "blocked", on_fail, add.stderr)
            return add.returncode
        committed = run(["git", "commit", "-m", str(data["commit_message"])])
        if committed.returncode != 0:
            notify_many(clerk, job, "blocked", on_fail, committed.stdout + committed.stderr)
            return committed.returncode
        commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        if data.get("push"):
            pushed = run(["git", "push"])
            if pushed.returncode != 0:
                notify_many(clerk, job, "blocked", on_fail, pushed.stderr)
                return pushed.returncode

    github_closed = False
    comment = data.get("issue_comment") or ""
    issue = data.get("issue") or (job if str(job).isdigit() else None)
    repo = github_repo()
    if comment and issue and repo:
        gh_api("POST", f"/repos/{repo}/issues/{issue}/comments", {"body": comment})
        gh_api("PATCH", f"/repos/{repo}/issues/{issue}", {"state": "closed"})
        github_closed = True

    for rel in data.get("temp_cleanup") or []:
        path = safe_cleanup(str(rel))
        if path.is_file():
            path.unlink()
    handshake.unlink(missing_ok=True)
    (jobs_dir() / f"{job}.run.json").unlink(missing_ok=True)

    notify_many(clerk, job, "git", on_pass, f"commit={commit or 'none'} closed={github_closed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
