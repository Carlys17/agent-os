# Scheduling

AgentOS scheduling lets you run recurring or one-time agent work from the
gateway. Use it for reminders, periodic summaries, status checks, channel
updates, and webhook-delivered automation.

Scheduling is managed with the `agentos cron` command group.

## Requirements

Scheduled jobs run through the gateway:

```sh
agentos gateway run
```

For long-lived local use, start the managed gateway:

```sh
agentos gateway start --json
agentos gateway status
```

## List Jobs

```sh
agentos cron list
agentos cron list --agent main
agentos cron list --json
```

Job visibility is scoped to the selected profile, not to the session that
created each job. Calls from the Control UI, CLI, or a paired channel therefore
see the same profile-wide schedule list. The creation session is retained as
delivery metadata and shown as **Created from** when available.

## Add an Interval Job

Run a prompt every hour:

```sh
agentos cron add \
  --every 1h \
  --text "Summarize important project updates" \
  --name hourly-project-check
```

Intervals accept values such as `30s`, `5m`, and `1h`.

## Add a Cron Expression

Run on weekdays at 09:00 in a named timezone:

```sh
agentos cron add \
  --cron "0 9 * * 1-5" \
  --tz "America/Los_Angeles" \
  --text "Prepare a short morning brief" \
  --name weekday-morning-brief
```

Use `--exact` when you do not want the default stagger.

## Add a One-Time Job

```sh
agentos cron add \
  --at "2026-06-01T09:00:00+00:00" \
  --text "Remind me to review the launch checklist" \
  --name launch-checklist-reminder
```

## Job Kinds

`--job-kind` decides what actually happens when a job fires. It defaults to
`auto`, which resolves to `reminder` for normal targets, `system_event` for
`--session-target main`, and `script` when you pass `--script`.

| Kind | What fires | Spends tokens |
| --- | --- | --- |
| `reminder` | Your `--text` is delivered verbatim. Nothing else runs. | No |
| `script` | A file in `~/.agentos/scripts/` runs; its stdout is delivered. | No |
| `agent_turn` | The agent runs `--text` as a prompt and its reply is delivered. | Yes |
| `system_event` | The text is written into the main session and wakes the heartbeat. | Yes |

An `agent_turn` job can also carry a `--script`, which then runs *before* the
turn as a data collector — see [Pre-run scripts](#pre-run-scripts).

The default matters: `agentos cron add --every 1h --text "Summarize updates"`
creates a **reminder**, so it repeats that sentence every hour rather than
summarizing anything. Add `--job-kind agent_turn` when you want the agent to do
the work.

## Run a Script Instead of a Model

A `script` job is the watchdog shape — poll something on a timer, deliver a line
when it matters, stay quiet otherwise — with no model in the loop:

```sh
mkdir -p ~/.agentos/scripts
cat > ~/.agentos/scripts/watch-memory.sh <<'EOF'
#!/usr/bin/env bash
used=$(ps -A -o %mem | awk '{s+=$1} END {printf "%d", s}')
[ "$used" -gt 90 ] && echo "⚠ memory at ${used}%"
EOF

agentos cron add --every 5m --script watch-memory.sh --name memory-watchdog
agentos cron update <job-id> --script watch-disk.sh
```

The script path is **relative to `~/.agentos/scripts/`**. Absolute paths, `~`,
and `..` are refused, and a symlink that leaves the directory is refused at run
time — the directory is the trust boundary. `.sh` and `.bash` run under bash;
every other extension runs under the same Python interpreter as the gateway.
Pass `--workdir` to run somewhere other than the script's own directory.

Arguments go through `--script-arg`, repeated once per argument:

```sh
agentos cron add --every 15m --script watch_rss.py --name hn-watch \
  --script-arg --name --script-arg hn \
  --script-arg --url --script-arg https://news.ycombinator.com/rss
```

They are passed to the script as argv with no shell in between, so a value
containing spaces or `;` stays one argument and cannot start a second command.
The Web UI takes them as one line and splits it the way a shell would.

The bundled **cron-watchers** skill ships ready-made scripts for the common
sources (RSS/Atom, a JSON endpoint, a GitHub repo) that already follow this
contract — ask the agent for it, or see
`agentos skills view cron-watchers`.

What the job does with the result:

- **stdout** → delivered verbatim, exactly as printed (capped at 16k characters).
- **no stdout** → silent run. Nothing is delivered and the run counts as a
  success, so a watchdog that prints only on trouble stays quiet.
- **a final line of `{"wakeAgent": false}`** → also treated as silence, so
  watchdog scripts written for other runtimes work unchanged.
- **non-zero exit or timeout** → the error is delivered *and* the job fails, so
  a broken watchdog cannot be mistaken for a quiet one. `--timeout` bounds the
  run (default 600s).

Secrets are masked in both stdout and stderr before delivery, and AgentOS's own
controls (`AGENTOS_GATEWAY_TOKEN` and the redaction/sensitive-path switches) are
withheld from the child process. Provider credentials are *not* — a script
inherits `OPENAI_API_KEY` and friends exactly like every other AgentOS child
process, which is what lets a watcher call a model API of its own. Set
`AGENTOS_STRIP_PROVIDER_ENV=1` to withhold those too.

**What you are accepting.** The script runs on this host as you, on schedule,
with nobody watching and no approval prompt — there is no model deciding what to
run, but also nothing reviewing it. Treat `~/.agentos/scripts/` as trusted as
your shell profile, and remember that anything with write access to that
directory can schedule itself. For that reason a script job can only be created
by an interactive CLI or Web caller: the in-agent `cron` tool refuses
`job_kind='script'` from a channel, which keeps a chat message from scheduling
unattended execution.

Script jobs never take `--elevated` — elevation only means something for a job
that runs an agent turn.

## Pre-run Scripts

The other half of the same idea: keep the script, but let an agent read what it
found instead of the user. Add `--script` to an `agent_turn` job and it runs
first, as a data collector:

```sh
agentos cron add --every 10m --name repo-triage \
  --job-kind agent_turn \
  --script watch_github.py \
  --script-arg --repo --script-arg owner/name \
  --script-arg --scope --script-arg issues \
  --text "Summarize anything here that looks urgent. Stay brief."
```

Per tick:

- **stdout** → prepended to the prompt as `## Script output`, then the turn runs
  with your `--text` after it.
- **no stdout** (or a `{"wakeAgent": false}` final line) → the turn is skipped
  entirely. No model call, no session, no transcript line, no delivery. This is
  what makes the pattern cheap: the agent only wakes on ticks with news.
- **non-zero exit** → the error is prepended as `## Script error` and the turn
  runs anyway, so the agent can tell the user the collector broke.

Same directory rule, same argv handling, and the same operator gate as a script
job. The script's stdout is untrusted input arriving inside a prompt — the
header says so to the model, and a cron turn's read-only tool surface is the
real containment. Think twice before combining a pre-run script that reads the
open internet with `--elevated`.

## Choose the Session Target

The default target is an isolated session. For most scheduled work, that is the
least surprising option.

Useful targets:

| Target | Use when |
| --- | --- |
| `isolated` | Each scheduled run should stand alone. |
| `session` | You want to deliver into a specific session configured by the runtime surface. |
| `current` | The job should continue in the session that created it (requires a bound session). |
| `main` | You want a system event for the main session. |

Example:

```sh
agentos cron add \
  --every 30m \
  --session-target isolated \
  --text "Check for urgent channel updates" \
  --name urgent-update-check
```

## Delivery

Disable delivery:

```sh
agentos cron add \
  --every 1h \
  --text "Create a private summary" \
  --no-deliver \
  --name private-hourly-summary
```

Deliver through a webhook:

```sh
agentos cron add \
  --every 1h \
  --text "Post a compact status summary" \
  --webhook-url https://example.com/hooks/agentos \
  --webhook-token-env AGENTOS_WEBHOOK_TOKEN \
  --name webhook-status-summary
```

Prefer `--webhook-token-env` or `--webhook-token-file` over inline tokens so
secrets do not land in shell history.

## Inspect and Run Jobs

```sh
agentos cron status <job-id>
agentos cron runs <job-id>
agentos cron runs <job-id> --limit 50
```

Run a job immediately:

```sh
agentos cron run <job-id> --yes
```

## Update or Remove Jobs

```sh
agentos cron update <job-id> --enabled
agentos cron update <job-id> --disabled
agentos cron update <job-id> --every 2h
agentos cron remove <job-id> --yes
```

Primary delivery destinations are not patched in place from the CLI. Remove and
re-add a job when the primary channel or webhook destination needs to change.

## Troubleshooting

Check the gateway and job state:

```sh
agentos gateway status
agentos cron list
agentos cron status <job-id>
agentos cron runs <job-id>
```

If a job posts to a channel, also check:

```sh
agentos channels status
```

A `script` job that appears to do nothing is usually working as designed: empty
stdout means silence. `agentos cron runs <job-id>` distinguishes the two — a
silent run is recorded with a `silent: script produced no output` summary, while
a broken script is recorded as a failure with the exit code and stderr.

Read next:

- [`channels.md`](channels.md)
- [`operations.md`](operations.md)
- [`troubleshooting.md`](troubleshooting.md)

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/use-agent-os/agent-os/issues/new?template=docs_report.yml)
