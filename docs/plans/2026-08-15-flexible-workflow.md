# herdr-collab 灵活性升级实施计划（2026-08-15 grilling 定案）

> 给实施 agent：本计划是自包含的，不需要任何对话上下文。仓库 = 本文件所在仓库（`D:\VscodeWorkSpace\deploy-project\skills\herdr-collab`，GitHub: YYHCOPPOLO/herdr-collab）。术语先看根目录 `CONTEXT.md`。
>
> **纪律（强制）**：本机一切操作走 Python 脚本或 Git Bash，**禁止 PowerShell/cmd**；删除文件用 Python（os.remove/shutil.rmtree，注意 git 对象只读要先 chmod）；临时产物写到调用方项目的 `temp/`（没有就放系统 temp，跑完即删）。

## 已定决策速查

| # | 决策 | 结果 |
|---|---|---|
| R1 | 痛点 | 角色/名字硬编码、handshake 手写易错、finish_run 表达力、失败循环无升级、无票间依赖 |
| R1 | 复杂度红线 | **保持薄封装**：不加配置文件、不做编排引擎 |
| R1 | 拓扑 | 同 repo 多窗口（多 worker/多 clerk 并行），不做跨 repo |
| R2 | agent 类型识别 | 用 herdr 原生 `agent` 字段，删 `CODING_KINDS` 名单 |
| R2 | 角色写死 | 清掉 `notify --phase done` 特判、missing-handshake 写死 main-grok 这两处 |
| R2 | handshake | 加 `init` 子命令生成骨架 + `handoff` 前自动校验 |
| R2 | finish_run | 命令条目升级为可选对象，加 `soft` / 单条 `timeout_sec` / 单条 `env`；**不做条件步骤** |
| R2 | 失败循环 | 只做**升级**（`max_bounces` 默认 3，超限后 blocked 通知加发 lead）；**不做盲重试** |
| R2 | 票间依赖 | 纯消息链（A 的 on_pass → lead → lead 派 B），只写文档 |
| R3 | spawn | 加 `spawn` 子命令（pane split → agent start → rename，全 herdr 原生） |
| R3 | 状态外露 | clerk 开始/结束收工包时用 `pane report-metadata` 报当前 job；**不做桌面通知** |
| R3 | 多 clerk | 零代码，`handoff --to git-clerk-2`，只写文档 |

明确不做：条件步骤、盲重试、桌面通知、clerk 池/自动选闲、状态 dashboard、跨 repo 寻址、配置文件。

## 背景事实（实施时直接用，别再查）

- herdr 二进制：`D:\ProSoft\herdr\bin\herdr.exe`（env `HERDR`/`HERDR_HOME`/PATH 解析）。所有控制命令返回 JSON 信封 `{"id":..., "result":{...}}`。
- **agent 检测**：`herdr agent get <name>` 返回的记录里，识别出 coding agent 时有非空 `agent` 字段（值为 kind 名如 `"kimi"`）；裸 shell 无此字段、`agent_status` 恒 `unknown`。
- `agent start <NAME> --kind <KIND> --pane <id>`：要求目标 pane 处于交互 shell 提示符，就绪才返回（默认超时 30s）；kind 共 21 种（grok/kimi/claude/codex/omp…）。
- `pane split [pane] --direction right|down [--cwd] [--no-focus]`：返回新 pane id。pane 内 agent 可用环境变量自称：`HERDR_PANE_ID` 等。
- agent/pane 名字必须匹配 `[a-z][a-z0-9_-]{0,31}` 且全局唯一。
- `pane report-metadata` 可往侧栏写自定义字段——**确切 flags 以 `herdr pane report-metadata --help` 为准**（本计划不替它编语法）。
- pane 无 `agent` 字段时 `agent rename <pane_id> <name>` 可能失败；裸 shell 改名用 `pane rename`。

## 实施项（每项一个 commit，顺序执行）

### 1. agent 检测原生化 + 角色写死清理（scripts/herdr_peer.py、scripts/herdr_finish.py）

- `herdr_peer.py`：删 `CODING_KINDS` 常量；`is_coding_agent(target)` 改为「`agent_record(target)` 的 `agent` 字段非空」。`occupant_kind` 保留（inbox 元信息/展示用）。
- `herdr_peer.py` `cmd_notify`：删掉 `phase == "done"` 改道 `cmd_handoff` 的特判（要交接就显式 `handoff`）。`--phase` 的 choices 保留 `done`（纯标签）。
- `herdr_finish.py` `main()`：握手文件缺失时的 notify 目标从写死 `["main-grok"]` 改为 `["--worker 参数"] if args.worker else ["main-grok"]`（worker 忘写握手，优先退回工人）。
- 单测：`is_coding_agent` 用构造记录覆盖（有/无 `agent` 字段）。

### 2. `init` 子命令 + handoff 前校验（两个脚本）

- 校验逻辑抽到 `herdr_finish.py`：`validate_handshake(data: dict, job: str) -> list[str]`，返回问题列表（空 = 通过）。覆盖现有全部前置校验：status ∈ {pass, ok, ""}、env 是对象、timeout_sec 正数、temp_cleanup 逐项过 `safe_cleanup`；新增：job 与文件名一致、`from` 非空。`main()` 改为调用它，有问题就 notify on_fail 退回（退出码 2，行为与现状一致）。
- `herdr_peer.py` 顶部 `from herdr_finish import safe_cleanup, validate_handshake`（同目录脚本直接 import 可行：脚本自身目录在 `sys.path[0]`）。
- `herdr_peer.py` 新增 `init --job <id> [--from <name>] [--lead main-grok] [--clerk git-clerk]`：在 `jobs_dir()` 写 `<id>.done.json` 骨架——status/from/lead/clerk/on_pass/on_fail 预填，`files`/`finish_run`/`temp_cleanup` 空数组，`commit_message`/`issue_comment` 空串，`issue` null，`push` false。已存在则拒绝覆盖，除非 `--force`。打印文件路径。
- `cmd_handoff`：deliver 给 clerk **之前**先 `validate_handshake`，有问题直接打印问题列表并退出码 2（不打扰 clerk），提示工人修回执。
- 单测：validate_handshake 各坏例；init 骨架字段与 --force 行为（用 `HERDR_JOBS` 指临时目录）。

### 3. finish_run 对象命令（scripts/herdr_finish.py）

- 条目允许三种形态：字符串 / 数组 / 对象 `{"cmd": <字符串|数组>, "soft": false, "timeout_sec": <秒>, "env": {...}}`。对象三键全可选；`cmd` 必填。
- `parse_command` 改名/扩展为解析条目返回 `(argv, soft, timeout_override, env_override)`；对象形态的 `cmd` 再按字符串/数组规则解析。校验（第 2 项）同步识别对象形态：`cmd` 缺失/类型错 = 问题。
- 执行语义：单条 `timeout_sec` 覆盖 job 级；单条 `env` 在 job 级 `env` 之上再合并。`soft: true` 的命令失败（非零退出**或超时**）不中断：run_log 记 `{"command":..., "exit":rc|124, "soft":true}`，继续下一条；成功路径的 run.json 增加 `soft_failures` 计数；成功 notify 消息末尾追加 `soft失败=N`（N>0 时）。
- 解析失败（引号不闭合等）仍属握手畸形，硬退回，不受 soft 保护。
- 单测：三种形态解析、soft 失败继续、单条 timeout/env 覆盖、soft 超时不中断。

### 4. 失败升级 max_bounces（scripts/herdr_finish.py）

- 握手可选 `max_bounces`（默认 3，须为正整数，校验覆盖）。
- bounce 计数持久化在 `.herdr/jobs/<job>.run.json`：每次**执行类失败**（命令非零退出/超时/命令不存在）或 **GitHub 失败**导致退回前，读旧 run.json 的 `bounces`（无则 0）+1 写入新 run.json。握手校验失败（退出码 2）与 abort（3）不计数。
- 退回时若 `bounces > max_bounces`：blocked notify 的目标 = `on_fail + on_pass`（去重），消息末尾加「退回次数超限（N/M），lead 请介入」。
- 成功路径清零无所谓（文件归档带走）。
- 单测：计数递增、超限加发 on_pass、未超限不加。

### 5. `spawn` 子命令（scripts/herdr_peer.py）

- `spawn --name <name> [--kind <kind>] [--pane <id>] [--cwd <dir>] [--timeout MS]`：
  1. 客户端先校验 name 匹配 `[a-z][a-z0-9_-]{0,31}`；
  2. `pane split`（目标 pane：`--pane` 指定，缺省用 `--current`；`--no-focus`；`--cwd` 透传）拿到新 pane id；
  3. 给了 `--kind`：`agent start --kind <kind> --pane <新id> [--timeout]`，然后 `agent rename <新id> <name>`；没给（裸 shell 工人）：`pane rename <新id> <name>`；
  4. 打印 `{"name", "pane", "kind"}` JSON。
- `agent start` 失败/超时：报错并保留 pane（不替用户收拾，消息里给出新 pane id 让人能查）。
- 确切 flags 以 `herdr pane split --help` / `herdr agent start --help` 为准。
- 单测只覆盖 name 校验；真 spawn 依赖活 herdr，验收走人工冒烟（见下）。

### 6. clerk 状态外露（scripts/herdr_finish.py）

- `main()` 在通过校验、开跑 `finish_run` 之前：若环境变量 `HERDR_PANE_ID` 存在，调 `pane report-metadata` 给本 pane 报「running job `<id>`」（确切 flags 用 `--help` 确认；调用失败只 print 不影响流程，herdr 不在时静默跳过）。
- 收工（成功归档后）与退回（所有失败返回点）各报一次对应状态（如 `blocked job <id>` / `done job <id>`）。实现成一个 `report_state(text)` 小函数，统一容错。
- 单测：HERDR_PANE_ID 不存在时 report_state 无操作不抛错（mock run 或直接短路判断）。

### 7. 文档与术语

- `SKILL.md`：
  - Talk 一节命令列表加 `init`/`spawn`/`abort` 示例；
  - Handshake 一节：JSON 示例加 `max_bounces`；Defaults 段补「命令条目可为对象 `{"cmd","soft","timeout_sec","env"}`」「退回次数超 max_bounces 后 lead 会被加进 blocked 通知」；
  - 新增「Chain tickets」小节：A 票 `on_pass` → lead → lead 派 B 票，依赖不入引擎；
  - 新增一句多 clerk 说明：再起命名窗口 `git-clerk-2`，`handoff --to git-clerk-2`；
  - Hard rules 加一条：升级不是重试——clerk 永不原样重跑失败命令。
- `README.md`：What it does 加 spawn/init 两条；Quick start 各加一行示例；How a ticket flows 补 bounce 升级与软失败。
- `CONTEXT.md`：加 **Spawn** 词条；**Escalation** 词条补 max_bounces 默认 3。

## 验收

1. `py -m unittest discover -s tests` 全过（现有 11 项 + 新增）。
2. 烟囱（在临时 git 仓库 + `HERDR_JOBS` 指临时目录，参照上次做法）：成功/失败/超时/GitHub 失败重跑幂等/abort 五路全过，**新增**：
   - soft 失败继续且成功 notify 含 soft失败=1；
   - max_bounces=1 时第二次退回的通知目标含 lead；
   - handoff 一个缺 `from` 的握手 → 退出码 2、clerk 没收到任何东西；
   - `init` 生成的骨架能被 `herdr_finish` 直接校验通过（填上 files/finish_run 后跑通）。
3. 人工冒烟（活 herdr）：`spawn --name smoke-w1 --kind <本机有的 agent>` 能开窗口并命名；确认后 `pane close` 收掉。
4. 两个脚本 `py <script> --help` 正常。

## 提交纪律

- 每个实施项一个 commit；commit message 用英文 conventional 风格（与本仓库历史一致：`feat: ...` / `refactor: ...`）。
- 全部完成后 `git push`。
- 收尾：把本仓库最新内容同步到使用方项目的 `.agents/skills/herdr-collab/`（排除 `.git`/`__pycache__`/`.herdr`），本项目 `temp/` 里本次的产物删掉。
