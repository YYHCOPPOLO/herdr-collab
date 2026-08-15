#!/usr/bin/env python3
"""Clerk finish package: execute the handshake, never diagnose failures."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PEER = Path(__file__).resolve().with_name("herdr_peer.py")

DEFAULT_TIMEOUT_SEC = 180  # per finish_run command; long suites set timeout_sec in the handshake
GIT_PUSH_TIMEOUT_SEC = 120


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


def run(
    args: list[str],
    *,
    env: dict | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(repo_root()),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
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
            time.sleep(1.5)
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


def parse_command(command) -> list[str]:
    """A command in string form -> argv, split with POSIX quoting rules (shlex).
    Use the array form for paths or arguments with special characters."""
    if isinstance(command, list):
        return [str(part) for part in command]
    return shlex.split(str(command))


def parse_entry(entry) -> tuple[list[str], bool, float | None, dict | None]:
    """One finish_run entry -> (argv, soft, timeout_override, env_override).

    Forms: "string" (POSIX quoting), ["argv", ...], or an object
    {"cmd": <string|array>, "soft": bool, "timeout_sec": n, "env": {...}}
    with all three object keys optional.
    """
    soft = False
    timeout = None
    env = None
    command = entry
    if isinstance(entry, dict):
        if "cmd" not in entry:
            raise ValueError("对象形态缺 cmd")
        command = entry["cmd"]
        soft = bool(entry.get("soft", False))
        if entry.get("timeout_sec") is not None:
            timeout = float(entry["timeout_sec"])
            if timeout <= 0:
                raise ValueError(f"timeout_sec 必须为正：{entry['timeout_sec']!r}")
        if entry.get("env") is not None:
            if not isinstance(entry["env"], dict):
                raise ValueError("条目 env 必须是对象")
            env = {str(k): str(v) for k, v in entry["env"].items()}
    argv = parse_command(command)
    if not argv:
        raise ValueError("空命令")
    return argv, soft, timeout, env


def finish_env(extra: dict) -> dict | None:
    if not extra:
        return None
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in extra.items()})
    return env


def write_run_log(job: str, run_log: list, proc=None, note: str = "") -> Path:
    payload = {"job": job, "ok": False, "runs": run_log}
    if note:
        payload["note"] = note
    if proc is not None:
        payload["stdout"] = (proc.stdout or "")[-4000:]
        payload["stderr"] = (proc.stderr or "")[-4000:]
    log = jobs_dir() / f"{job}.run.json"
    log.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def validate_handshake(data: dict, job: str) -> list[str]:
    """Pre-flight checks shared by the clerk (herdr_finish) and handoff
    (herdr_peer). Returns a list of problems; empty means runnable."""
    problems = []
    if str(data.get("job") or "") != str(job):
        problems.append(f"job 字段 {data.get('job')!r} 与文件名 {job} 不一致")
    if not str(data.get("from") or "").strip():
        problems.append("from 为空（谁干的活）")
    if str(data.get("status") or "").lower() not in ("pass", "ok", ""):
        problems.append(f"status={data.get('status')!r} 不是 pass/ok")
    if not isinstance(data.get("env") or {}, dict):
        problems.append('env 必须是对象（{"NAME": "value"}）')
    try:
        timeout = float(data.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
        if timeout <= 0:
            raise ValueError("non-positive")
    except (TypeError, ValueError):
        problems.append(f"timeout_sec 非法：{data.get('timeout_sec')!r}")
    for rel in data.get("temp_cleanup") or []:
        try:
            safe_cleanup(str(rel))
        except SystemExit as exc:
            problems.append(str(exc))
    for command in data.get("finish_run") or []:
        try:
            parse_entry(command)
        except (TypeError, ValueError) as exc:
            problems.append(f"finish_run 条目非法 {command!r}: {exc}")
    return problems


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
        target = [args.worker] if args.worker else ["main-grok"]
        notify_many(clerk, job, "blocked", target, f"missing {handshake}")
        return 1
    data = json.loads(handshake.read_text(encoding="utf-8"))
    worker = data.get("from") or args.worker or "sub-grok-1"
    lead = data.get("lead") or "main-grok"
    clerk = data.get("clerk") or clerk
    on_fail = list(data.get("on_fail") or [worker])
    on_pass = list(data.get("on_pass") or [lead])

    # Abort sentinel: someone cancelled this job before the clerk started.
    abort = jobs_dir() / f"{job}.abort"
    if abort.exists():
        abort.unlink()
        handshake.unlink(missing_ok=True)
        notify_many(clerk, job, "other", on_pass, f"#{job} 已取消（发现 {abort.name} 哨兵），收工包未执行。")
        return 3

    # Validate the handshake before doing any work; a malformed package bounces immediately.
    problems = validate_handshake(data, job)
    if problems:
        notify_many(clerk, job, "blocked", on_fail,
                    "握手校验未过：\n" + "\n".join(f"- {p}" for p in problems)
                    + "\n修好后更新回执再 handoff。")
        return 2
    extra_env = data.get("env") or {}
    timeout_sec = float(data.get("timeout_sec", DEFAULT_TIMEOUT_SEC))

    run_log = []
    for command in data.get("finish_run") or []:
        try:
            argv, soft, cmd_timeout, cmd_env = parse_entry(command)
        except (TypeError, ValueError) as exc:
            log = write_run_log(job, run_log, note=f"unparseable finish_run {command!r}: {exc}")
            notify_many(clerk, job, "blocked", on_fail, (
                f"命令解析失败：{command!r}（{exc}）。字符串按 POSIX 引号规则拆分；"
                f"含路径/特殊参数请改用数组或对象形式。日志：{log.as_posix()}。"
            ))
            return 2
        effective_timeout = cmd_timeout if cmd_timeout is not None else timeout_sec
        env = finish_env(extra_env)
        if cmd_env:
            if env is None:
                env = os.environ.copy()
            env.update(cmd_env)
        try:
            proc = run(argv, env=env, timeout=effective_timeout)
        except FileNotFoundError:
            log = write_run_log(job, run_log, note=f"command not found: {argv[0]}")
            notify_many(clerk, job, "blocked", on_fail, f"找不到命令：{argv[0]}。日志：{log.as_posix()}。")
            return 127
        except subprocess.TimeoutExpired:
            entry_log = {"command": command, "exit": 124, "timeout_sec": effective_timeout}
            if soft:
                entry_log["soft"] = True
                run_log.append(entry_log)
                continue
            run_log.append(entry_log)
            log = write_run_log(job, run_log, note=f"timeout after {effective_timeout}s")
            notify_many(clerk, job, "blocked", on_fail, (
                f"命令超时（{effective_timeout:.0f}s）：{command}。日志：{log.as_posix()}。"
                "需要更长时限就在回执里调大 timeout_sec。"
            ))
            return 124
        entry_log = {"command": command, "exit": proc.returncode}
        if soft:
            entry_log["soft"] = True
        run_log.append(entry_log)
        if proc.returncode != 0:
            if soft:
                continue
            log = write_run_log(job, run_log, proc)
            notify_many(clerk, job, "blocked", on_fail, (
                f"执行失败，原样退回（clerk 不查、不改代码）。"
                f"命令：{command} exit={proc.returncode}。日志：{log.as_posix()}。"
                "修好后更新回执再 handoff。"
            ))
            return proc.returncode

    soft_fails = sum(1 for r in run_log if r.get("soft"))
    (jobs_dir() / f"{job}.run.json").write_text(
        json.dumps({"job": job, "ok": True, "runs": run_log, "soft_failures": soft_fails},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    files = [f for f in (data.get("files") or []) if f]
    commit = ""
    if files and data.get("commit_message"):
        add = run(["git", "add", "--", *files])
        if add.returncode != 0:
            notify_many(clerk, job, "blocked", on_fail, add.stderr)
            return add.returncode
        staged = run(["git", "diff", "--cached", "--quiet"])
        if staged.returncode == 0:
            # Nothing staged: either a rerun after a partial success or the files
            # did not change. Skip the commit instead of failing on "nothing to commit".
            commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        elif staged.returncode == 1:
            committed = run(["git", "commit", "-m", str(data["commit_message"])])
            if committed.returncode != 0:
                notify_many(clerk, job, "blocked", on_fail, committed.stdout + committed.stderr)
                return committed.returncode
            commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        else:
            notify_many(clerk, job, "blocked", on_fail, f"git diff --cached exit={staged.returncode}: {staged.stderr}")
            return staged.returncode
        if data.get("push"):
            try:
                pushed = run(["git", "push"], timeout=GIT_PUSH_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                notify_many(clerk, job, "blocked", on_fail, f"git push 超时（{GIT_PUSH_TIMEOUT_SEC}s）")
                return 124
            if pushed.returncode != 0:
                notify_many(clerk, job, "blocked", on_fail, pushed.stderr)
                return pushed.returncode

    github_closed = False
    comment = data.get("issue_comment") or ""
    issue = data.get("issue") or (job if str(job).isdigit() else None)
    repo = github_repo()
    if comment and issue and repo:
        try:
            gh_api("POST", f"/repos/{repo}/issues/{issue}/comments", {"body": comment})
            gh_api("PATCH", f"/repos/{repo}/issues/{issue}", {"state": "closed"})
            github_closed = True
        except Exception as exc:  # noqa: BLE001
            log = write_run_log(job, run_log, note=f"github comment/close failed: {exc}")
            notify_many(clerk, job, "blocked", on_fail, (
                f"commit 已完成（{commit or '无改动'}），但 GitHub 评论/关票失败：{exc}。"
                f"网络恢复后更新回执再 handoff 即可（重跑幂等，不会重复 commit）。日志：{log.as_posix()}。"
            ))
            return 1

    # Notify first, then archive job files — evidence survives a failed notify.
    msg = f"commit={commit or 'none'} closed={github_closed}"
    if soft_fails:
        msg += f" soft失败={soft_fails}"
    notify_many(clerk, job, "git", on_pass, msg)

    for rel in data.get("temp_cleanup") or []:
        path = safe_cleanup(str(rel))
        if path.is_file():
            path.unlink()
    archive = jobs_dir() / "archive"
    archive.mkdir(exist_ok=True)
    for artifact in (handshake, jobs_dir() / f"{job}.run.json"):
        if artifact.exists():
            artifact.replace(archive / artifact.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
