---
name: cron
description: "Use when the user asks to schedule recurring tasks, one-off reminders, timers, or cron-style jobs through the AgentOS cron tool."
always: false
triggers:
  - schedule
  - recurring
  - timer
  - cron
  - every
  - reminder
  - remind
  - 提醒
  - 每分钟
  - 每5分钟
  - 每天
  - 定时
provenance:
  origin: openclaw-derived
  license: MIT
  upstream_url: https://github.com/openclaw/openclaw
  maintained_by: AgentOS
metadata:
  agentos:
    requires_tools:
      - cron
---

# Cron Skill

When the user asks to schedule something, set up a recurring task, create a timer, or create a reminder, use the `cron` tool.

The `schedule` argument is a **structured object**, not a string. Choose one shape and translate any natural language yourself before calling the tool — the tool will not parse free-form text and will reject flat strings with a structured error.

Three accepted schedule shapes:

- `{"kind": "cron", "expr": "<5-field POSIX cron>", "tz": "<optional IANA timezone>"}`
  Recurring on a calendar pattern. Example: `{"kind": "cron", "expr": "0 9 * * 1-5", "tz": "Asia/Shanghai"}` for weekdays at 09:00 Shanghai wall time.
- `{"kind": "every", "every_seconds": <integer ≥ 1>}`
  Recurring on a fixed sub-minute or odd interval. Example: `{"kind": "every", "every_seconds": 30}` for every 30 seconds.
- `{"kind": "at", "at": "<ISO-8601 with timezone>"}`
  One-shot at an absolute time. The timestamp must include a timezone offset.

Translation examples (do this in your own reasoning before calling the tool):

- "每5分钟提醒我喝水" → `cron(action="add", schedule={"kind": "cron", "expr": "*/5 * * * *"}, task="喝水", job_kind="system_event", session_target="main")`
- "每30秒打印一次" → `cron(action="add", schedule={"kind": "every", "every_seconds": 30}, task="...", job_kind="agent_turn", session_target="isolated")`
- "明天早上9点叫我" → compute the absolute ISO-8601 string with timezone, then `cron(action="add", schedule={"kind": "at", "at": "<that ISO-8601>"}, task="...", job_kind="system_event", session_target="main")`
- "every weekday at 9am Los Angeles time" → `cron(action="add", schedule={"kind": "cron", "expr": "0 9 * * 1-5", "tz": "America/Los_Angeles"}, task="...")`

## Running a script instead of a model

`job_kind="script"` runs a file on schedule and delivers its stdout — no LLM
call, no tokens. The `script` must be a path relative to `~/.agentos/scripts/`;
`script_args` is a list passed as argv (never through a shell). Empty stdout
means the run stays silent, and a non-zero exit is delivered as a failure.

```
cron(action="add", schedule={"kind": "every", "every_seconds": 300},
     job_kind="script", script="watch-memory.sh")
```

`job_kind="agent_turn"` with a `script` is the other half: the script runs
first, its stdout becomes context for the turn, and a tick where it prints
nothing skips the turn entirely.

```
cron(action="add", schedule={"kind": "cron", "expr": "*/10 * * * *"},
     job_kind="agent_turn", script="watch_github.py",
     script_args=["--repo", "owner/name"],
     task="Summarize anything urgent.")
```

Either way, scheduling a script needs an interactive CLI or Web caller — it is
refused from a chat channel. The bundled `cron-watchers` skill ships scripts for
RSS feeds, JSON endpoints, and GitHub repos that already follow this contract.

## Where the job announces

By default a job reports back to the conversation it was created in, which is
what "remind me" means. Pass `delivery` only when the user names a different
destination:

```
cron(action="add", schedule={"kind": "cron", "expr": "0 9 * * 1-5"},
     job_kind="agent_turn", task="Summarize yesterday's incidents.",
     delivery={"mode": "channel", "channel_name": "telegram",
               "channel_id": "-1001234567890"})
```

- `mode="channel"` needs `channel_name` (the adapter key: `telegram`, `slack`,
  `discord`). `channel_id` is the id the *provider* uses — a Telegram numeric
  chat id, negative for a group, or `@username`. It is never an AgentOS session
  key like `agent:main:telegram:direct:1245463966`; the tool rejects those with
  the id you probably meant. Leave `channel_id` empty to use the channel's
  configured default chat. `account_id` and `thread_id` are optional, and
  `best_effort: true` keeps a failed delivery from failing the run.
- `mode="none"` schedules a job that announces nowhere.
- `mode="origin"` (or omitting `delivery`) keeps the calling conversation.

Choosing a channel requires an interactive CLI or Web caller and a
`session_target` other than `main` — from a chat channel the job always
delivers back to that same conversation. Do not invent a chat id: if the user
has not given one, ask, or leave it empty for the channel default.

The `add` response echoes the resolved `delivery`, so confirm the destination
from that rather than assuming it.

Other actions:

- List: `cron(action="list")`.
- Trigger now: `cron(action="run", job_id="<job id>")`.
- Cancel: `cron(action="remove", job_id="<job id>")`.

Cron expression format: `minute hour day month weekday` (e.g. `0 9 * * 1-5` = weekdays at 9am).
