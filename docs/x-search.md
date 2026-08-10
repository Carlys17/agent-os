# X (Twitter) Search

The `x_search` tool searches X posts, profiles, and threads. It is backed by
xAI's server-side `x_search` tool on the Responses API at
`https://api.x.ai/v1/responses`: Grok runs the search against X's index and
returns a synthesized answer with citations to the posts it used.

Reach for it instead of `web_search` when you want current discussion,
reactions, or claims **on X**. General web pages still belong to `web_search`
and `web_fetch`.

## What it is not

- **Not a search provider.** `agentos search list` covers the providers behind
  `web_search`, which return ranked pages. `x_search` returns an answer plus
  citations, so it is a separate tool and cannot be selected as a `web_search`
  backend.
- **Not a write path.** It cannot post, reply, like, DM, upload media, delete,
  or read your authenticated X account. AgentOS ships no authenticated X
  surface; an `x_search` answer is never evidence that anything was written.
- **Not model-agnostic.** Only xAI has access to X's post index. Your agent can
  run on any provider — the tool makes its own call to xAI regardless.

## Credentials

An xAI API key, and nothing else:

| Path | How |
| --- | --- |
| `XAI_API_KEY` | Set it in `~/.agentos/.env` or the gateway environment. |
| Pasted key | `agentos configure x-search --api-key <key>`, or the Setup page. |

SuperGrok / X Premium+ OAuth is **not** supported. Hermes Agent accepts it;
AgentOS has no OAuth subsystem, so `credential_source` in the result is always
`"xai"`.

Without a reachable credential the tool is removed from the model's schema
entirely. That is deliberate: every tool schema is fixed overhead on every
provider call, so an install with no xAI key should not pay for this one. It
also means "the agent says it has no x_search tool" is the expected behaviour
before setup, not a bug.

`agentos context` still lists and prices `x_search`. That command reports what
each *profile* would cost across the whole registry and does not model
credential gating — `image_generate` appears there the same way without an
image provider. The live per-turn surface is the one that drops it.

## Cost

`x_search` bills your xAI account directly. It does not pass through the
AgentOS provider layer, so the spend does **not** appear in `agentos cost` or
the Usage view. Watch it in the xAI console.

## Configure

```sh
agentos onboard catalog x-search
agentos configure x-search --api-key-env XAI_API_KEY
agentos configure x-search --x-search-model grok-4.5 --x-search-reasoning-effort low
agentos configure x-search --no-x-search-enabled
```

The Setup page carries the same fields under Capabilities → X (Twitter) search.
Saving applies immediately; no gateway restart.

```toml
[x_search]
enabled = true
# Any Grok model with access to xAI's server-side x_search tool.
model = "grok-4.5"
base_url = "https://api.x.ai/v1"
api_key = ""
api_key_env = "XAI_API_KEY"
# "", low, medium, high, or xhigh. Empty uses the model's own default;
# xhigh is only accepted by models that document it.
reasoning_effort = ""
# One attempt. A complex X search runs 60-120s.
timeout_seconds = 180.0
# Hard wall for the whole call including retries.
total_timeout_seconds = 300.0
# Retried on 5xx, timeout, and connection errors only.
retries = 2
```

`base_url` exists for an HTTPS proxy that speaks xAI's Responses API. A
non-HTTPS URL, or one pointing at a cloud metadata endpoint, is rejected and
the default is used — the request carries a bearer token.

## Tool parameters

| Parameter | Type | Description |
| --- | --- | --- |
| `query` | string (required) | What to look up on X. |
| `allowed_x_handles` | string[] | Include these handles exclusively (max 10). A leading `@` is stripped. |
| `excluded_x_handles` | string[] | Exclude these handles (max 10). Cannot be combined with `allowed_x_handles`. |
| `from_date` | string | `YYYY-MM-DD` start date. |
| `to_date` | string | `YYYY-MM-DD` end date. |
| `enable_image_understanding` | boolean | Ask xAI to analyze images attached to matching posts. |
| `enable_video_understanding` | boolean | Ask xAI to analyze videos attached to matching posts. |

Dates are checked before the HTTP call. A malformed value, an inverted range,
or a `from_date` in the future fails immediately rather than spending a
billable call that could only return nothing. A future `to_date` is allowed —
"from yesterday to tomorrow" is a legitimate way to catch posts as they arrive.

## Result

```json
{
  "success": true,
  "provider": "xai",
  "credential_source": "xai",
  "tool": "x_search",
  "model": "grok-4.5",
  "query": "reactions to the new Grok image features",
  "answer": "...",
  "citations": ["https://x.com/..."],
  "inline_citations": [{ "url": "...", "title": "...", "start_index": 0, "end_index": 42 }],
  "degraded": false,
  "degraded_reason": null
}
```

### `degraded` is the field that matters

xAI answers with HTTP 200 and a fluent, confident answer even when its X index
matched nothing for your filters. That answer comes from the model's training
data and is indistinguishable from a real one by shape alone.

`degraded` is `true` when a narrowing filter (`allowed_x_handles`,
`excluded_x_handles`, `from_date`, `to_date`) was active **and** both citation
channels came back empty. Treat that answer as unsourced: it is not something
found on X. A broad query with no citations is not degraded — it is just an
answer.

Common causes:

- A typo in a handle, or an account that does not exist.
- A date range too narrow, or sliding past the posts you wanted.
- An index gap. Some active accounts intermittently fail to surface even when
  they post regularly; retry after a few minutes.

## Policy and limits

- Member of `group:web`, so `deny = ["group:web"]` cuts the route to api.x.ai
  along with the other network tools.
- On the cron allowlist, next to `web_fetch` and `web_search` — a scheduled job
  watching X is the obvious use, and the tool can only read.
- Classified `external` for result budgeting, so a long answer is trimmed under
  the same per-turn ceiling as other network results.
- Runs under the `web.fetch` sandbox action kind.

## Troubleshooting

**The agent says it has no `x_search` tool.** No credential resolved. Check
`agentos env list` for `XAI_API_KEY`, or that `[x_search] api_key` is set, and
that `enabled` is not `false`.

**`x_search is not enabled for this model`.** The configured `model` lacks
access to xAI's server-side tool. Switch back to `grok-4.5` or another Grok
model that documents it.

**Timeouts.** `timeout_seconds` bounds one attempt; `total_timeout_seconds`
bounds the whole call. Retries stop when the remaining budget cannot fit
another attempt, so raising `retries` alone does nothing unless the total goes
up too.

## See also

- [`search.md`](search.md) — general web search providers.
- [`tools-and-sandbox.md`](tools-and-sandbox.md) — the built-in tool catalog.
- [`configuration.md`](configuration.md) — every config key.
