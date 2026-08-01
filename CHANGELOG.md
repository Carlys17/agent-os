# Changelog

All notable changes to AgentOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- `[auxiliary]` configures the model for work AgentOS runs on its own behalf
  rather than as part of a turn — analysing an attached document, describing an
  image. Empty values reuse `[llm]`, so an install that never sets it is
  unchanged; point it at something cheap when those tasks do not need your main
  model. Per-task overrides live in `[auxiliary.tasks.<task>]` (`document` and
  `vision` today), because a text-only model cannot describe an image.

- The system prompt now names the developer tools that actually exist on the
  machine. An agent asked to run the tests reached for `pytest` and found out it
  was missing by running it and reading a shell error, which cost a turn and
  often started a repair for a problem that was never the task. The block is
  probed once per process and lives in the cached part of the prompt, so it is
  paid for once per session rather than once per turn. Only names are emitted,
  never paths. Turn it off with `[prompt] env_probe_enabled = false`.

- `agentos context` shows what every provider request carries before the
  conversation starts. Tool schemas dominate that overhead — about 7,300 tokens
  on a stock install, charged on every call in every turn — and nothing
  surfaced the number, so the only way to learn it was to write a script
  against the registry. The command breaks the cost down, lists the largest
  schemas, and prices each `[tools] profile` against the current one.

- `[tools] profile` is now documented. It already narrowed the tool surface
  sharply — `coding` costs 77% less than `full`, `messaging` 92% less — but it
  appeared in no example config, no doc page and no operator guide, so the
  largest available lever on per-request cost was undiscoverable. Because a
  profile is fixed for the session, narrowing it does not disturb the prompt
  cache.

- A turn that edits code and then answers "done" without running anything is
  now noticed. A passive ledger records which files a turn changed and whether
  a test, build or lint command ran *after* the last change; when the model
  stops on unverified edits the turn emits a warning naming the files and the
  omission. Evidence gathered before an edit does not count for it. Prose,
  data and config files are excluded — a README edit has nothing a test could
  exercise — and messaging surfaces are exempt, since answering a person in
  chat is not maintaining a checkout.

### Changed

- `edit_file` no longer fails on text that differs from the file only in
  formatting. It still tries an exact match first, then falls back through a
  chain of increasingly permissive strategies — indentation, whitespace runs,
  unescaped `\n` literals, smart quotes, and finally block similarity — and
  names the strategy that matched in its result. Text that appears more than
  once is still rejected rather than guessed, now with the line numbers of
  every match, and a failed edit reports the closest regions it found.

- The progress watchdog now sees repeated *successful* calls, not only repeated
  failures. An agent reading the same file over and over produced a clean result
  every time, so by every measure the turn was making progress while burning
  iterations and context on nothing. A call is counted as a repeat only when its
  result is byte-identical to the previous one for the same tool and arguments —
  re-reading a file that changed is real work, and its differing result resets
  the count.

### Fixed

- Tool schemas from MCP servers went to the provider exactly as the server
  emitted them, so one malformed tool could fail the whole request and take
  every other tool down with it. Schemas are now normalized once at discovery:
  `$ref` into `$defs` is inlined, `anyOf`/`oneOf` unions that exist only to
  permit `null` collapse to their concrete branch, `"type": ["string", "null"]`
  becomes `"string"`, objects without `properties` gain an empty one, and
  values that are not schemas at all are dropped along with any `required`
  entry naming them.

- Side-task LLM calls spent tokens that nothing recorded. Analysing a document
  and describing an image each built their own provider client, so the cost
  appeared on the provider bill but never in `agentos cost`. Those calls now run
  through one auxiliary client that bills the session that triggered them and
  additionally records them under an `aux:<task>` scope, keeping runtime cost
  separable from turn cost. Two copies of the provider-to-credential mapping in
  `tools/builtin/media.py` collapse into one — the document path had only ever
  read the environment, so it ignored a key configured in `[llm]` for the same
  provider and now finds it.

- A side task with no reachable API key sent the request anyway and failed on
  `Illegal header value b'Bearer '`, which named neither the provider nor the
  variable to set. It now fails before the request with both. Local backends
  such as Ollama, which authenticate by reachability rather than by key, are
  unaffected.

- A failing provider request read its error body whole. That body is written by
  whatever sits in front of the provider — a WAF's HTML block page, a proxy's
  stack trace — and has no size contract, so the read was unbounded; on the
  Anthropic path the entire decoded body then became the `ErrorEvent` message
  and flowed into the agent's context. Error bodies are now read to a bound and
  summarised: JSON keeps its `error.message`, an HTML page collapses to its
  title and size, and anything else is truncated with the cut made visible.

## [2026.7.31] - 2026-07-31

### Changed

- Onboarding router tier defaults move up a generation across all three
  gateway profiles (`openrouter`, `bankr`, `opencap`): C1 goes from
  `minimax-m3` to `gpt-5.6-luna` and C3 from `claude-opus-4.8` to
  `claude-opus-5`. On the OpenRouter profile C0 moves to
  `deepseek/deepseek-v4-flash` so C0 and C1 do not collapse onto the same
  model and the cheap tier keeps its purpose. `claude-opus-5` is registered
  in the model catalog and pricing tables, so its context window is 1M rather
  than the 200K default and the usage tracker reports real cost.
  `minimax-m3` stays as the `image_model` vision route and is deliberately
  left out of the migration maps, which apply to every tier including
  `image_model` (#169).

- The Pilot Router docs now describe the C0–C3 tiers — what each tier is for,
  which model each gateway profile assigns to it, and how to pick one — and
  the OpenCAP routing page no longer mentions `oc-uncensored-1.0` (#170).

### Fixed

- Any skill that called an authenticated HTTP API was dead on arrival. The
  outbound guard matched credential-ish *names*, so `http_request` refused
  every `Authorization` and `x-api-key` header, and `exec_command` refused
  `{"sellToken": …}` (a web3 asset, not a token), `grep "token: "`, and
  `CAP_API_KEY=$(jq -r …)` — while a real key pasted inline passed through.
  With no working call path and no approval route, the model routed around it
  by writing the key to a file and running that, which the guard never
  inspected (#165).

  The guard now matches credential **values** — a PEM block, a
  vendor-prefixed provider key, a DSN password, an `/etc/passwd` line — and
  leaves names alone. An opaque API key in a header is how authenticated APIs
  work and is no longer refused. The shell check runs only on commands that
  can reach the network, mirroring the gate `execute_code` already applied.
  Blocks now name a working alternative instead of dead-ending, and
  `AGENTOS_SENSITIVE_PAYLOAD_DISABLED=1` turns the check off.

  What replaces the pattern match is a credential path: a skill declares
  `metadata.requires.env`, and those names — and only those — are forwarded
  into `execute_code`'s sandbox for the session that loaded the skill, so the
  value never enters the transcript. A skill AgentOS did not ship cannot
  declare one of AgentOS's own provider keys.

### Added

- Command output is scanned for credentials before it reaches the model.
  `exec_command`, `background_process` and `process(action=log)` mask
  vendor-shaped keys, auth headers, JWTs, private keys and DSN passwords.
  File content gets a non-reusable sentinel rather than a head/tail mask, so
  an agent that reads a key and writes it back cannot silently corrupt it.
  `AGENTOS_REDACT_SECRETS=0` disables it; the value is read once at startup so
  a command cannot switch it off mid-session.

- `AGENTOS_STRIP_PROVIDER_ENV=1` withholds AgentOS's provider credentials from
  child processes. Off by default because bundled skills read those names from
  `os.environ`.

### Security

- `AGENTOS_GATEWAY_TOKEN` and the sandbox guard switches no longer reach
  child processes. Every `exec_command` previously inherited `os.environ`
  verbatim, including the token that authenticates to the control plane.

- `http_request` now refuses cloud metadata endpoints (`169.254.169.254`,
  `metadata.google.internal`, ECS task credentials). The repo already shipped
  an SSRF guard and `web_fetch` used it, but `http_request` validated only the
  URL scheme. Ordinary private addresses stay reachable — unlike `web_fetch`,
  this is the tool people point at a local dev server on purpose.

## [2026.7.30] - 2026-07-30

### Added

- Native support for Capminal Skills (`Capminal/agent-skills`) in the Skills
  hub: browse, inspect, and install allowlisted Capminal skills with publisher
  branding, carried by a Capminal brand mark that falls back cleanly when the
  logo cannot be fetched (#144).

### Changed

- Runtime dependencies in `pyproject.toml` now carry upper bounds, so a major
  release of a dependency cannot land in an install that was resolved against
  the previous one (#153).

### Fixed

- The agent could not tell which of its installed skills applied to a request,
  and answered from general knowledge instead. Four separate causes, each of
  which alone was enough to produce that:

  - The prompt budget was a cliff. One skill over it and *every* description in
    the block was dropped for a name-only list — a 27k render fell to 3.5k
    against a 24k budget, so 20k of the configured allowance bought nothing and
    the model had never seen a single description. Descriptions are now
    shortened to the longest length that fits (the widest, not the first that
    works: 451 chars where a fixed step would have settled for 320), and skills
    are only dropped once even a names-only list overruns. A default install
    was unaffected; the cliff was reached by installing skills, which is
    backwards.
  - Names-only mode told the model to call `skill_view` on every entry that
    might be relevant — up to one call per skill, which no model will do — and
    never mentioned `skill_list`, which returns every description in one call.
    It now points at `skill_list`, and only when the session actually has it.
  - With prompt caching on (the default), the block was delivered as a *user*
    message headed "not a user request … use it only when it is relevant",
    contradicting its own "read this before answering" from the weakest
    position in the request. When the skill list is the same every turn
    (relevance filtering off, the default) it now belongs to the cacheable
    system prompt instead, which is also where it is cheapest.
  - Scheduled (cron) turns received the block but not `skill_view` or
    `skill_list`, so following it was impossible. Both tools — read-only — are
    now on the cron allowlist.

- Asking for a skill that is not installed read as a broken tool. `skill_view`
  answered with what *not* to do and "tell the user the skill is not installed",
  offering no next step even when a configured hub carries the skill and the
  tools to fetch it are in the session — so a model dressed the dead end up as a
  failure, reporting that `skill_view` "returned error: 14", a code that exists
  nowhere in AgentOS. It now says the lookup worked and the skill simply is not
  here, names installed skills with similar names, and points at
  `skill_search_community` — only when the session can actually reach it, and
  always as an offer to install rather than an instruction to (#162).

- Reading a large skill cost the whole skill. `skill_view` returned every byte
  of a SKILL.md, and unlike the system prompt a tool result is not cached, so a
  56 000-character hub skill spent ~14 000 tokens per read and again on every
  re-read — the shape behind reports of skill loading being slow and expensive.
  Over `[skills].max_skill_view_chars` (new, default 10 000) it now returns the
  skill's opening sections plus an index of the rest, read on with
  `skill_view(name, section="<title>")`. Across the skills on a real install
  that is 43% fewer characters, and 80–87% on the largest. Shipped skills are
  unaffected: the largest is 21 600 characters and the median 2 400. A body with
  no headings, or one only slightly over the ceiling where the index would cost
  more than it saves, is still returned whole.

- A skills block that quietly lost its descriptions was indistinguishable from
  an operator uninstalling skills: nothing was reported as dropped and the
  character count simply fell. Each turn now records `skills_render_mode` and
  `skills_description_max_chars` in the decision log, and any render below
  `full` is logged as `skills_filter.budget_degraded` with what to change.

- A skill's linked files were named with the platform separator, so on Windows
  the index offered `references\api.md`. A model quotes that back as
  `file_path`, where the backslash is a JSON escape, and it matches neither the
  tool call nor how a `SKILL.md` writes its own links. Paths are emitted as
  POSIX now. Nothing was unreadable — the reader already normalised separators;
  the defect was in what the agent was told to type.

- Skill cards in the Web UI overflowed their grid tracks and changed height
  with their content, so the hub grid reflowed as cards loaded. The card layout
  is fixed now and long text is contained rather than pushing the track wider
  (#135, #161).

- The **Installed** chip in the skill detail dialog did not reflect whether the
  skill was actually installed (#121).

## [2026.7.29] - 2026-07-29

### Added

- Bankr skills published from bankr.bot — the ones that live under an author's
  wallet address instead of in the `BankrBot/skills` repository — can now be
  browsed and installed like any other hub skill, starting with
  `stock-premium-lp-manager`. They arrive as JSON with the body inline, so the
  `SKILL.md` is synthesized from the payload rather than downloaded from a
  repository, and the skill is credited to its author rather than inheriting
  Bankr's brand. As with the repository half, only allowlisted skills can be
  installed through the Bankr source, so it cannot be used to pull an arbitrary
  author's skill and record it as having come from Bankr's hub.

### Security

- `SECURITY.md` now answers what happens to an audit report: findings go
  through the private advisory form rather than a pull request adding an audit
  document to the repository, there is no bug bounty program, and a researcher
  whose report leads to a fix is credited in that fix's release notes (#154).

## [2026.7.28] - 2026-07-28

### Added

- A new chat can be started from anywhere in the console with
  `Cmd/Ctrl+Shift+O`, using the same flow as the New Chat button. The button
  tooltip shows the platform-appropriate hint (#131, closes #120).

### Fixed

- The settings screen called itself three different things depending on where
  you looked. The route title, sidebar item, page heading, browser tab title,
  and the docs now all say **Agent Setup** (#125, closes #123).

## [2026.7.27] - 2026-07-27

### Added

- A variable reported as missing is now checked against the places a
  credential may already live. If `gh auth login` has been run, `GITHUB_TOKEN`
  is reported as available from the GitHub CLI and can be imported with
  `agentos env import GITHUB_TOKEN` or a button on the Environment screen.
  Checking runs `gh auth status`, never `gh auth token`, so nothing reads a
  secret to decide whether one exists; importing only happens when asked for.
- When a skill's requirements are unmet, `skill_view` appends a setup note
  saying what is missing and what to do about it — and what to do depends on
  who is listening. A chat channel is told a secret must not be collected
  there because it would be stored in the conversation; an unattended run is
  told to continue and state what does not work; an interactive session gets
  the actual command. The skill still loads either way.
- Environment variables can be managed from AgentOS instead of by hand-editing
  `~/.agentos/.env` and restarting. Every surface that could already *detect* a
  missing variable can now *fix* it: a new **Environment** screen in the Web UI
  (`/env`), an `agentos env list|get|set|unset` command, `env.*` gateway RPC,
  and a **Set &lt;VAR&gt;** action in the Skills dialog next to the existing
  install action. Setting a variable applies it to the running gateway, so a
  skill that was ineligible for want of one becomes eligible without a restart.
- Skill manifests can describe the variables they need — a description, where
  to obtain the value, and whether it is a secret — instead of only naming
  them. Existing manifests using the plain `requires.env: [NAME]` list keep
  working unchanged.
- Skills can also declare non-secret settings under `metadata.agentos.config`,
  stored in the TOML config under `[skills.config]` rather than in `.env`.
  Their current values are appended to what `skill_view` returns, so the agent
  starts from what is configured instead of asking.
- The agent has `env_list` (names and set/unset state, never values) and, gated
  behind the approval queue and hidden by default, `env_set`. There is no
  reveal tool: a model that can read back stored credentials is one prompt
  injection away from exfiltrating them.
- "Is the agent actually being offered this skill?" is now a question with an
  answer. Every skill row from the gateway, and every line the agent's own
  skill listing prints, carries whether the skill is offered and — when it is
  not — which of six reasons applies: model invocation is disabled in its
  manifest, a requirement is missing, a tool it needs is not enabled in this
  session, a native tool supersedes it as a fallback, relevance filtering
  skipped it for this message, or the injected skills block was full. The
  explanation is one sentence naming what to do, and it never contains a
  filesystem path. Ready and offered were previously the same green dot, which
  is why a perfectly installed skill could sit there being silently withheld.
  Five of the six answer from the installed set alone, so the Skills page shows
  them before you send anything; only the relevance-filtering one needs a
  message to rank against and stays in the decision log.
- With `[tools] enabled = false`, skills that require a tool are now reported as
  withheld rather than available. The Skills page previously answered against
  everything the install could offer while chat answered against a turn with no
  tools at all — the same skill, two answers.
- How a skill was acquired — `shipped` with AgentOS, installed from a `hub`, or
  a `local` directory you added — is now a fact AgentOS records and reports,
  alongside the source, identifier, version, and install time for hub installs.
  It is derived from the install record rather than guessed from which
  directory the files sit in, so moving a skill does not change the story of
  where it came from.
- The same record answers whether Update and Remove will actually work. A
  hub-installed skill whose files no longer sit where the lockfile recorded
  them keeps Update — an update re-fetches by identifier — and loses Remove,
  because AgentOS will not delete files it cannot prove it owns. The Web UI
  says so instead of offering a button that fails.
- Skills can name a publisher, so a partner's skills carry that partner's
  identity whether they shipped with AgentOS or you installed them from that
  partner's hub. Publishers are allowlisted **inside AgentOS**: a `SKILL.md` or
  a hub catalog can only *select* a recognized publisher by id, never describe
  one. A third-party skill that writes a partner's name, URL, and logo into its
  own frontmatter renders as an ordinary unbranded skill. Selecting an id is
  restricted too: only a skill shipping inside the release may name its own
  publisher, and an installed one is branded by the hub catalog row it came
  from, so a directory dropped into a skills path can never appear as a
  partner. Publisher is independent of provenance — one says whose name is on a
  skill, the other where the text came from and under what licence.
- `agentos skills list --json` gained `publisher` and `acquisition`, built by
  the same code the gateway and the Web UI use. It deliberately has no
  `availability` key: that depends on a chat session's tool surface, which a
  CLI process does not have, and an absent key means "not computed" rather than
  "not offered".

### Changed

- The Skills screen's Installed tab now groups cards by where a skill came
  from — **Partners**, **Shipped with AgentOS**, **Installed from a hub**,
  **Your local skills** — instead of by which directory holds the files. The
  storage layer is still shown, as a chip on each card, because it decides
  which skill wins a name collision; it no longer decides the heading. If you
  navigated by the old `Bundled` / `Managed` headings, the cards under them are
  now under `Shipped with AgentOS` and `Installed from a hub`.
- `skills.max_skills_prompt_chars` now defaults to **24000**, up from 8000. The
  bundled skill set renders to about 16k characters with descriptions, so the
  old default silently forced every default install past the budget and into
  name-only mode — the model had never seen a skill description on a stock
  install. Raise it further if you install many skills; lower it if you run a
  model with a small context window, where the whole-request ceiling can be
  smaller than this budget. See
  [configuration.md](docs/configuration.md#skill-prompt-budget).

### Security

- Environment writes are refused for names that steer subprocess execution
  (`PATH`, `LD_PRELOAD`, `PYTHONPATH`, `EDITOR`, …) or AgentOS runtime posture
  (`AGENTOS_AGENT_PERMISSIONS`, `AGENTOS_GATEWAY_TOKEN`, `AGENTOS_STATE_DIR`,
  …). Every tool AgentOS spawns inherits `os.environ` and several guards are
  read from it, so a writable surface without this gate could widen what the
  agent is allowed to do. The gate applies on write only — values set in your
  shell or by editing the file directly keep working, and the `AGENTOS_` prefix
  is not blanket-blocked.
- Listings never carry a value. `env.reveal` is a separate method, rate limited
  to five per thirty seconds and written to the audit log.
- The Hermes migration wrote the migrated `.env` at the default umask, leaving
  imported credentials world-readable on a typical box. It now writes `0600`,
  like every other `.env` AgentOS creates.

### Upgrade notes

- Two `.env` lines that AgentOS previously ignored now take effect: a
  bash-style `export KEY=value`, and the first entry in a file saved with a
  byte-order mark. Both were parsed into unusable keys before (literally
  `export KEY`, and `\ufeffKEY`), so the variable was not set. If your `.env`
  has either, expect that variable to start being applied — which is what the
  line was written to do. Values exported in your shell still win over the
  file, so nothing that was already working changes.
- CLI logs now go to stderr instead of stdout. Anything capturing a command's
  stdout to collect log output needs `2>` instead; in exchange, `--json`
  output is parseable on an install that has a populated `.env`.
- The skill snapshot cache is invalidated once on first run, so the first
  command after upgrading rescans skills from disk.

### Removed

- The session-flush subsystem is gone. It wrote a "flush receipt" before
  destructive compaction and never earned its keep: roughly 8,000 lines for a
  memory path that underperformed. Compaction still records a durable
  checkpoint first, so the pre-image it recovers from is unchanged.
- The `memory.flush_*` and `memory.repair_*` configuration keys are no longer
  read. An existing `agentos.toml` keeps working — the keys are dropped on load
  with one warning naming them, and the file is rewritten on the next config
  save. They will be rejected outright in 0.2.0.

  Removing `memory.flush_enabled`, `memory.flush_compaction_safety_mode`, and
  `memory.flush_compaction_requires_safe_receipt` matters most. With no flush
  service left, no receipt can ever be written, so `flush_enabled = true`
  combined with `block` (or the legacy `requires_safe_receipt`) would have made
  compaction demand a receipt nothing could produce: refused on every turn,
  context window filling until the provider errors, with a single warning line
  as the only clue.
- `sessions.reset` and `sessions.contextCompact` no longer return a
  `flush_receipt` field, and `agentos reset` no longer prints a "Flush mode"
  line. Both described work that no longer happens.

### Fixed

- `env_key` is not always a variable name: providers that authenticate by
  OAuth carry the literal string `"OAuth"`, which put a variable called
  `OAuth` on the Environment screen that nobody could set.
- `skill_list` no longer tells the model to call `env_set`, which is hidden by
  default and so usually not callable — the same dead-end this feature exists
  to remove.
- A `.env` value with significant leading or trailing whitespace was written
  unquoted and then silently trimmed when read back. The OpenClaw migration
  carries a command allowlist across, and its entries are prefix patterns:
  `"^pytest "` with the trailing space matches that command, while `"^pytest"`
  without it matches anything starting with those six characters. Migrating an
  allowlist and quietly widening it is the wrong direction.
- `.env` parsing now recognises the bash-compatible `export KEY=value` form.
  A hand-written `export GITHUB_TOKEN=…` was previously invisible to AgentOS,
  and a save would have appended a second, competing definition.
- `/reset` in the standalone chat TUI works again on sessions with a non-empty
  transcript. It had been gated on a flush service that is never constructed,
  so it aborted every time; `/compact` printed a matching false warning.
- The skills block no longer writes an absolute filesystem path for every
  skill into the system prompt. Nothing read it — skills are looked up by name,
  and the skill-reading tool explicitly tells the model not to go looking on
  disk — while it accounted for roughly two thirds of the block and put the
  user's home directory in front of the model on every turn. Removing it, with
  the raised budget above, is what lets a stock install list every skill with
  its description.
- Upgrading lifts an existing `skills.max_skills_prompt_chars = 8000` to the new
  default. The key is materialised into every saved `config.toml`, so raising the
  default alone would have reached new installs only, and 8000 is exactly the
  value that cannot fit the shipped skills' descriptions. The rewrite runs with
  the config migrations on the next gateway start, takes the usual timestamped
  backup, and touches only that exact old default — a budget someone chose is
  left alone.
- A skill that appears in a skills directory while the gateway is running is
  now picked up on the next turn instead of at the next restart. The cache was
  only cleared through AgentOS's own install paths, but the directories are
  shared: `agentos skills install` runs in a separate process, and
  `~/.agents/skills` is written to by other agents on the same machine. A skill
  from either was on disk, absent from `skills.list`, absent from the prompt,
  and unmentioned in any log. The cache is now validated against the same
  file manifest the on-disk snapshot already used, which costs one stat sweep —
  measured at 0.6 ms for 65 skills — on each load.
- `~/.agents/skills` and `<project>/.agents/skills` are honoured when they are
  created after startup. Both resolved once at boot and a missing one collapsed
  to "no such layer", so the first cross-agent install on a machine stayed
  invisible until a restart. The managed directory was already exempt for this
  exact reason; these two now match it.
- The guidance above the skills list no longer argues against using it. It
  opened with "Skills are optional task playbooks" and told the model to load
  one "only when a listed entry clearly matches" — while the same block, in the
  compact mode a stock install always fell into, listed nothing but names. A
  bare name matches nothing clearly, so the instruction could not be followed
  and the honest reading was "skip it". The two failure modes are not
  symmetric: loading a skill that turned out to be unnecessary costs a little
  context, and skipping one that carried the right endpoints, commands, or
  conventions produces a confidently wrong answer. The block now says so, asks
  the model to load on partial relevance, and — when only names are listed —
  states plainly that a name is not enough to rule a skill out.
- When the skills block does overflow its budget, the skills it drops are no
  longer chosen by load order, which always landed the cut on the skills an
  operator had installed. The cut now follows layer precedence, so `extra` and
  then `bundled` skills go before the ones in a writable skills path. The drop is
  also reported instead of being silent: a `skills_filter.budget_truncated`
  warning naming the dropped skills, and a `prompt_budget` reason on each
  affected skill.
- The skill count and skill-id list in turn metadata and the
  `skills_filter.applied` log counted skills that the budget had already thrown
  away, so the one place that could have revealed the problem asserted
  everything was fine.
- Setting an environment variable or installing a missing binary now takes
  effect for the agent without a gateway restart, which is what the
  Environment feature promised. The chat path built one eligibility cache at
  import time and remembered a *negative* lookup for the life of the process,
  while every other surface rebuilt its own per call — so the Skills screen
  reported a skill as ready while the agent refused to be given it, forever.
- Browsing or searching a skill hub now also shows skills you already installed
  from that source, including ones its catalog does not list. A skill installed
  from a GitHub URL used to vanish from the page it was installed on, because
  an empty browse never returned a row for it.
- The Installed marker in the community list no longer goes stale after a
  removal, and no longer fires on a catalog entry whose *name* happens to match
  an unrelated skill's install *identifier*. Names are matched against
  installed names and identifiers against installed identifiers.
- Installing a skill while a search is open no longer loses the row when the
  search is cleared, and the skill dialog no longer unmounts itself when the
  list underneath it changes.
- A failed hub search reports the failure instead of rendering as "no skills
  match your query", and results the hub matched on a tag are no longer
  discarded by a second client-side filter that could not see the tag.

## [2026.7.26] - 2026-07-26

### Added

- Curated memory now nudges itself. Every N user turns — default 10,
  configured at `[memory.nudge]`, `interval = 0` disables it — a short
  background review runs after the reply is already on the wire and saves
  anything durable it found in the conversation. Machine traffic (cron,
  heartbeat, subagent, recall), the review turn itself, and turns where the
  agent already wrote to memory are excluded and do not advance the counter.
- OpenCAP is supported as an LLM gateway provider.
- Telegram shows a typing indicator while a turn is running.
- `SECURITY.md` documents GitHub private vulnerability reporting as the
  intake path for suspected vulnerabilities.

### Changed

- **Breaking:** channel authorization is now two connection surfaces —
  Control and Channel — backed by explicit RPC audiences, replacing roles and
  scopes. Telegram pairing is durable, group admission is explicit, and
  grants are revalidated before turns and tools. Owner/admin elevation is
  gone from tools, cron, the CLI, and the Control UI; sandbox and approval
  policy are unchanged. Channel roles, scoped tokens, access modes, and
  unauthenticated public Control are removed — existing configs using them
  need to move to pairing surfaces.
- Cron job management is scoped to the active profile, so jobs from one
  profile are no longer listed or mutated from another.
- Daily notes that the injection budget would discard are no longer read at
  all, cutting per-turn memory I/O.

### Fixed

- `/new` and `/reset` are non-destructive when flush is unavailable: the
  session is no longer discarded on a path that cannot produce a receipt,
  and compaction only demands a flush receipt when flush can actually
  produce one.
- The `MEMORY.md` migration is non-destructive — an existing file is
  preserved rather than overwritten.
- Turn captures are written atomically, so an interrupted write can no
  longer leave a truncated capture behind.
- Curated memory writes are locked on Windows, the injection scan covers a
  wider set of paths, and the hermes durability guards in the curated store
  are restored.
- `USER.md` counts as a memory source for write notifications.
- Unreadable curated files are surfaced as errors instead of being silently
  skipped, which previously left the agent blind to memory it could not
  read.
- The degraded-source list no longer grows one entry per failed metric.
- Slack dispatches Socket Mode slash commands and classifies slash-command
  conversations correctly.
- Discord completes native interaction responses and tolerates command
  registration failures instead of failing adapter startup.
- Telegram handles native bot-command mentions, preserves forum command
  reply targets, renders markdown replies, allows admitted DM slash
  commands, and keeps pairing runtime state serializable.
- Admitted senders are granted read access across channels.

### Removed

- Dream consolidation, the orphaned `flush_status`, the memory repair
  service, and the `agentos memory flush-session` command are removed.

## [2026.7.25] - 2026-07-25

### Added

- Added one fail-closed Control UI build contract,
  `python scripts/build_control_ui.py build`, for local source installs, CI,
  Docker, wheel/sdist publication, and wheelhouse releases. It requires
  Node.js 22 or newer, performs a clean locked npm install, enforces bundle
  budgets, generates an exact third-party license ledger, and verifies the
   resulting React bundle before packaging.
- OpenRouter's `openai/gpt-5.6-luna` is now the default LLM model.

### Changed

- The production Control UI is now the React 19 + Vite application on every
  route. Release wheels, source distributions, Docker images, and wheelhouse
  archives carry the same prebuilt, verified bundle; a missing or invalid
  bundle returns an actionable `503` instead of silently serving a different
  interface.
- Repository source builds and the provided source-install scripts now require
  Node.js 22 or newer and npm so they can build the Control UI before
  installing the Python package. Published wheels remain ready to run without
  Node.js.
- The SPA shell and runtime bootstrap are uncached while fingerprinted Vite
  assets are served with immutable caching. A runtime-injected base element
  lets one artifact serve `/control` and safe non-root custom prefixes,
  including deep-link refreshes; root, `/api`, and `/ws` prefixes are rejected
  because they overlap gateway routes.
- Guided setup and advanced configuration now share one Agent Setup workspace
  at `/control/settings`; the existing `/control/setup` and `/control/config`
  URLs remain compatibility routes, while adapter onboarding and credential
  validation now live with channel status and access management.
- Configuration clients now read one redacted `config.snapshot` and submit
  optimistic `expectedRevision` writes through a shared persist-first
  transaction. The gateway reports cumulative restart reasons, preserves
  write-only secret semantics, and provides explicit recovery when runtime and
  on-disk state diverge.

### Security

- The packaged Control UI now uses a same-origin Content Security Policy
  without `unsafe-inline` scripts. Theme initialization runs from a packaged
  pre-paint script; HTTP requests stay same-origin while explicit `ws:` and
  `wss:` remote-gateway profiles remain supported.
- Configuration snapshots never return stored secret values, and stale Control
  UI drafts fail closed when the active configuration changes on disk instead
  of overwriting an operator's out-of-band edit.

### Removed

- Retired the DingTalk, Matrix, QQ Bot, and WeCom channel adapters across the
  runtime, CLI, Web UI, configuration schema, install metadata, and current
  documentation. Supported messaging adapters are now Slack, Telegram, and
  Discord.
- Removed the retired Jinja Control UI template and its hand-maintained
  JavaScript, CSS, fonts, images, and vendored browser libraries. There is no
  legacy frontend fallback at runtime or in release artifacts.

### Fixed

- Control UI settings preserve the active configuration state, Bankr icons
  render correctly, and resetting a session reliably clears its client state.
- The collapsed Control UI sidebar toggle has improved interaction and layout.
- CLI onboarding prompts wrap correctly instead of overflowing narrow terminals.

## [2026.7.23] - 2026-07-23

### Added

- Mouse drag selection and copy in the full-screen `agentos chat` transcript:
  left-drag highlights text in the transcript pane and mouse-up copies the
  plain text (ANSI stripped, CJK width-aware) to the system clipboard via a
  cross-platform dispatcher (pbcopy, wl-copy, xclip, xsel, clip, OSC 52
  fallback) (#76).
- Rendering for reasoning-model think blocks in the CLI, with hidden tags and
  boundary markers so partial think content streams cleanly.

### Changed

- The waiting indicator is now turn-lifetime: it persists across the pre-token,
  mid-stream, and tool-call phases to give a consistent "agent is working"
  signal. `StreamingRenderer` uses the waiting indicator instead of a Rich
  `Live` instance, which removes ghost panel artifacts in Windows PowerShell.
- Markdown streaming keeps block and inline styles intact while preserving the
  raw buffer for downstream consumers.

### Fixed

- Telegram no longer deletes its persistent native command menu on adapter
  shutdown. Bot command menus are server-side configuration and must survive
  gateway restarts and overlapping adapter lifecycles (#74, fixes #52).

## [2026.7.22.post1] - 2026-07-22

### Added

- Managed MCP server configuration in the Web UI, with stdio, SSE, and
  Streamable HTTP transports, OAuth authorization, dynamic tool discovery, a
  Robinhood Trading preset, and a bundled safety-focused Robinhood skill (#66).
- Mouse-wheel scrolling and Home/End and Ctrl+A/Ctrl+E line navigation in the
  full-screen `agentos chat` interface (#67).

### Changed

- Promoted the MCP SDK to a standard dependency so remote MCP integrations work
  without installing an optional extra (#71).
- Renamed the Web UI chat assistant label from `Cap` to `AGENTOS` (#73).

### Fixed

- `agentos chat` full-screen transcript now responds to the first mouse wheel
  tick instead of needing several scrolls before the pane moves: the wheel step
  is larger and the tick that releases follow mode is compensated so the
  wrapped-line cursor leaves the viewport immediately (#69).
- Unauthenticated OAuth MCP servers no longer connect during gateway startup;
  authenticated servers continue to reconnect automatically (#72).
- MCP cancellation cleanup now closes partial Streamable HTTP and discovery
  state so slow or unavailable remote servers cannot leave open AnyIO contexts
  or crash gateway startup (#71, #72).

## [2026.7.22] - 2026-07-22

### Added

- `tools.enabled = false` provides an explicit plain-text mode for Ollama and
  other models that do not reliably implement native tool calls.

### Fixed

- `agentos chat` input frame now supports multiline input instead of
  submitting on every `Enter` (#62).
- Ollama multi-turn tool conversations now preserve assistant tool calls,
  correlate tool results by name, normalize native arguments, and retain the
  provider's model and completion reason, preventing repeated searches caused
  by malformed replay history (#44).
- Channel slash commands now render their RPC results instead of returning a
  generic `/<command> completed` acknowledgement; `/help` and `/history` also
  request the correct catalog/history payloads.
- Telegram Bot API sends retry transient connection failures before reporting
  delivery failure.

## [2026.7.20] - 2026-07-20

### Added

- `agentos chat` UX pass (issue #46):
  - The assistant speaker label now defaults to `agentos` (was hard-coded
    `cap`); override with the `AGENTOS_ASSISTANT_LABEL` env var. The
    label is sourced from a single place and consumed by the streamed
    `◢` marker, the pre-token waiting row, and the queued-turn marker.
  - Session display name now surfaces in the bottom toolbar
    (`title · model · [tier:cN]`) and `/status`. `/new <title>` persists
    the title as `SessionNode.display_name` so it survives a later
    `/resume`. The standalone `/new` path no longer drops the title
    silently (pre-existing bug).
  - `/c0` … `/c3` and `/auto` are now registered on both CLI surfaces
    (`cli_gateway`, `cli_standalone`). Gateway mode reuses the existing
    `router.hold.set` / `router.hold.clear` RPCs; standalone mutates the
    in-process `RouterControlHoldStore` directly.
  - The active Pilot Router tier hold shows in the bottom toolbar and in
    `/status` (or `auto` when no hold is set).
  - `SessionNode.derived_title` property fills the pre-existing dead
    hook, falling back `display_name → label → short opaque session id`.
  - The startup panel now renders `Session: <title> (<key>)` when a
    friendly title is known (plumbed through `StartupData` and the
    gateway welcome notice).
  - The active input row is now framed by a top and bottom rule
    (Claude Code style) so the typing area reads as a distinct box
    between the transcript and the bottom toolbar. Consistent across the
    gateway and `--standalone` surfaces.
  - Full-screen chat surface is now the **default** for `agentos chat`: the
    conversation renders in a scrollable in-app pane above a permanently-pinned
    input frame, so the frame stays visible while the assistant streams (no
    flicker, no dropped partial lines). The branded welcome screen (connect
    line + banner + tool/skill panel) renders at the top of the pane on launch
    — previously it was wiped by the alternate screen buffer. `PgUp`/`PgDn`
    scroll history; new output re-pins to the tail. Non-TTY / piped
    invocations fall back to native scrollback; `AGENTOS_CHAT_FULLSCREEN=0`
    forces native scrollback and `=1` forces full-screen.

### Changed

- The bottom toolbar now leads with the session title (or short key
  fallback) instead of only the opaque key segment, and shows the model
  alias after it.

### Fixed

- The framed chat input no longer balloons to fill the screen on a fresh
  launch. The input buffer window is pinned to a single row
  (`Dimension.exact(1)`) and a greedy spacer heads the layout, so the
  compact frame + toolbar stay pinned to the bottom of the terminal
  instead of the bottom rule + toolbar being pushed far below the
  `◢ you` row.
- `test_assistant_label_env_override` no longer wipes the subprocess
  environment (`PATH=""`), which crashed Python startup on Windows CI
  (`import _overlapped` → `WinError 10106`); it now layers the override
  on a copy of `os.environ`.

## [2026.7.19.post1] - 2026-07-19

### Changed

- Renamed the router display name from "AgentOS Router" to "Pilot Router"
  across the CLI, gateway, and onboarding surfaces.
- Synced the router docs with the `pilot-v1` default and the 3-option
  strategy selector.

### Removed

- The legacy `v4_phase3` router engine and its ~52MB model bundle no longer
  ship (Phase C): the module, the bundled weights, and the `lightgbm` /
  `joblib` / `scikit-learn` dependencies are gone from the wheel and the
  `recommended` / `ml-router` extras. A config that still pins
  `strategy = "v4_phase3"` keeps migrating to `pilot-v1` on load, and the
  removed `v4_bundle_dir` / `v4_use_aux_head` keys are ignored.

## [2026.7.19] - 2026-07-19

### Added

- Bundled `agentos` self-operation skill so the agent can drive its own
  AgentOS CLI and gateway. (#37)

### Changed

- AgentOS Pilot (`pilot-v1`), the self-trained on-device English router, is now
  the default router strategy. (#26)
- Router strategy migration: persisted `v4_phase3` selections are force-migrated
  to `pilot-v1` at gateway boot, and `v4_phase3` is dropped from the
  human-facing onboarding and router selectors. (#36)
- Bankr skills browse source: limited to two curated skills to avoid GitHub rate
  limiting, filled the skill descriptions, and added a brand-glyph logo
  fallback, a 📺 emoji avatar fallback, and an "Update" button backed by the
  `skills.update` RPC. (#39, supersedes #35)

### Fixed

- Skills UI: the installed badge desynced between cards after an install and
  reverted to "not installed" after a page refresh — installed skills are now
  matched by both name and identifier. (#39)
- Skill browsing crashed on an explicit JSON `null` description returned from the
  GitHub/Clawhub search boundary; the description now defaults safely. (#39)
- Local single-provider setups keep self-consistent router tiers, and several
  local-provider degrade gaps were closed (vLLM handling, empty-model honesty,
  and log visibility). (#30)

## [2026.7.18.post1] - 2026-07-18

### Fixed

- Release-hygiene re-cut of 2026.7.18. The initial 2026.7.18 tag only bumped
  `pyproject.toml`, so the repo's release-consistency guards
  (`tests/test_release_consistency.py`, `tests/test_install_scripts.py`) failed
  and the install docs/scripts still pointed at the prior tag. This post-release
  propagates the version across `uv.lock`, both consistency tests, `RELEASES.md`,
  `CHANGELOG.md`, the README install examples, and `install.sh`/`install.ps1`.
  No runtime code changes — the distributed software is identical to 2026.7.18.

## [2026.7.18] - 2026-07-18

### Added

- Interactive authentication provisioning when the gateway binds to a public
  interface: instead of refusing to start, `gateway start` now provisions a
  token interactively so a public bind is authenticated by default. `host` and
  `port` are configurable only via CLI flags (not runtime RPC). (#25)
- Browser-threat hardening for the gateway (#24). A loopback bind is not a
  boundary against a page in the operator's browser, so four fail-closed
  guards were added: a startup guard that refuses `auth.mode="none"` on a
  non-loopback bind (opt out with `auth.allow_unauthenticated_public=true`),
  WebSocket-handshake Origin validation (CSWSH), a `Host`-header allowlist
  (DNS rebinding), and an HTTP cross-origin guard on `/api/*`. Runtime
  `config.apply`/`config.patch` of `host` or `auth.mode` now reports
  `restartRequired: true`, since a host change does not rebind the live
  socket.

### Changed

- **BREAKING (opt-in deployments only):** the gateway now refuses to start
  when `auth.mode="none"` is combined with a non-loopback bind
  (`0.0.0.0`, a LAN IP, ...). If you deliberately run an unauthenticated
  gateway behind a reverse proxy / VPN / firewall, set
  `auth.allow_unauthenticated_public = true` (or
  `AGENTOS_AUTH_ALLOW_UNAUTHENTICATED_PUBLIC=true`). Default loopback
  deployments are unaffected. (#24)
- **BREAKING (opt-in deployments only):** `auth.mode="trusted-proxy"` no
  longer satisfies the public-bind guard. It only string-matched the
  client-suppliable `X-Forwarded-For` header (spoofable) and has no
  end-to-end resolver, so it did not actually authenticate. Use
  `auth.mode="token"` on public binds until real peer-IP validation ships.
  (#24)
- Reaching a loopback gateway through a custom hostname (e.g. an
  `/etc/hosts` alias to `127.0.0.1`) or a reverse-proxied Control UI now
  requires adding that origin to `control_ui.allowed_origins`; otherwise the
  `Host`/Origin guards reject it. The rejection message names the config key.
  (#24)

## [2026.7.17.post1] - 2026-07-17

### Fixed

- The `session_status` tool no longer fails on every call in a running
  gateway. It called `SessionManager.get_current_session()`, a method that
  exists only on test fakes and never on the production `SessionManager`, so
  the attribute access raised `AttributeError` and surfaced as
  `ToolError: Session manager not available`. It now resolves the calling
  session from the tool context — the same source the surrounding session
  tools already prefer — and loads it via `SessionManager.get_session()`.

## [2026.7.17] - 2026-07-17

### Added

- Curated memory stores, embedding refresh, and a pluggable memory
  provider layer (mem0). (#17)
- Restored the missing v4_phase3 local ML router bundle so the default
  router runs on-device instead of pinning to a single class, and
  corrected its attribution to OpenSquilla upstream. (#19)

### Changed

- Redesigned the Web UI chat transcript. (#15)

### Fixed

- `agentos memory embedding-download` now follows Hugging Face's CDN
  redirects. Every `resolve/main/...` URL answers with a 302 to a signed
  Xet CDN URL, but `httpx` does not follow redirects by default, so the
  download aborted with an `HTTPStatusError` before writing any data and
  the command never worked against the live API. (#20)

## [2026.7.15.post1] - 2026-07-15

### Added

- Partner-catalog skills system with a Bankr skills hub, and a
  Robinhood RWA address lookup skill (`robinhood-rwa-addresses`).

## [2026.7.15] - 2026-07-15

### Changed

- Relicensed the repository from MIT to **Apache-2.0** and added a root
  `NOTICE` file. Core modules derived from
  [OpenSquilla](https://github.com/opensquilla/opensquilla) (Apache-2.0)
  are now credited in `THIRD_PARTY_NOTICES.md`; the README credits
  OpenSquilla (built on) plus OpenClaw and Hermes Agent (influences).
  Wheels now ship `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md` in
  their dist-info license files.

## [2026.7.14.post1] - 2026-07-14

### Changed

- The Python distribution is now published to PyPI as **`use-agent-os`**
  (`uv tool install "use-agent-os[recommended]"`). The import package
  (`import agentos`) and the `agentos` CLI are unchanged. PyPI's project-name
  similarity rules reject `agentos`/`agent-os` variants (the bare name is held
  by an unrelated, abandoned 2022 project), hence the org-matching name.
- Built wheels are named `use_agent_os-<version>-py3-none-any.whl` (PEP 427
  normalization). Install scripts, the wheelhouse builder, the release
  workflow, and the README now reference the new filename; the README's
  primary terminal install is the PyPI command instead of a pinned wheel URL.

## [2026.7.14] - 2026-07-14

### Changed

- Re-release aligning the current version tag to 2026.7.14.
- Adopted CalVer versioning (`YYYY.M.D`). Because PEP 440 normalizes the version
  segment in wheel filenames (leading zeros dropped), tags use the same
  non-padded form, e.g. `v2026.7.15`.
- Install docs outside the README (`README.product.md`, `docs/quickstart.md`,
  `docs/mcp-server.md`, `docs/operations.md`) now point to the canonical README
  Installation section instead of duplicating version-pinned wheel URLs.

## [0.0.1] - 2026-07-05

Initial release of AgentOS.

### Core

- `agentos` Python package with the `agentos` and `gateway` CLI entry points.
- Unified gateway: one local Starlette server (`127.0.0.1:18791`) drives a
  single `TurnRunner` engine shared by the Web UI, the CLI, and every chat
  channel (Slack, Telegram, Discord, DingTalk, WeCom, Matrix, QQ). Tool
  calls, retries, approvals, and logs behave the same on every surface.
- Durable sessions, chat history, and replay data persisted in SQLite, with a
  per-agent workspace folder and bounded-depth subagents.

### Pilot Router

- Pilot Router picks the cheapest capable model tier (c0–c3) for each turn.
  The default `recommended` install ships the router; `AGENTOS_INSTALL_PROFILE=core`
  or `--router disabled` turns it off and routes every turn to one model.
- Two selectable routing strategies. The default `v4_phase3` runs an on-device
  ML ensemble (BGE embeddings + LightGBM) that scores each turn locally with no
  LLM call; the `recommended` / `ml-router` extras install its runtime
  dependencies. Its ~75MB model bundle is kept out of git and is not
  distributed with the repo or the wheel in this release, so unless the bundle
  is restored locally the router degrades gracefully — it logs a warning at
  boot and pins every turn to the default tier. The alternative `llm_judge`
  strategy classifies each turn (R0–R3) via a small LLM call — a cloud model or
  a local OpenAI-compatible endpoint (Ollama / LM Studio / llama.cpp / vLLM)
  set with `judge_model` / `judge_base_url` — and needs no local model files.
- Onboarding (Web UI wizard and CLI) offers the strategy via the Mode dropdown —
  "Pilot Router (Local ML)", "Pilot Router (LLM Judge)", or "Disabled". The
  "Judge model" field applies to, and appears only for, the LLM Judge strategy.
- `/c0`–`/c3` slash commands (web chat and messaging channels) pin the router
  to a tier for the current session; `/auto` restores automatic routing. These
  share the same short-lived hold store as the LLM-facing `router_control`
  tool via the `router.hold.set` / `router.hold.clear` gateway RPCs.
- The router auto-select visualisation mounts in a dock directly below the
  chat input bar and shows the latest turn's routing state.

### Providers

- Talks to 20+ LLM providers behind one config. **OpenRouter** is the default
  (`llm.provider = "openrouter"`, base URL `https://openrouter.ai/api/v1`,
  env `OPENROUTER_API_KEY`). The **Bankr LLM Gateway**
  (`https://llm.bankr.bot/v1`, env `BANKR_API_KEY`) is a selectable
  OpenAI-compatible gateway with its own tier profile. OpenAI, Anthropic,
  Ollama, DeepSeek, Gemini, DashScope/Qwen, Moonshot AI, Zhipu, Baidu Qianfan,
  and Volcengine Ark are also onboarding-verified.
- Model catalogs are fetched live from the provider's public endpoint at boot
  (context window, max output, vision support), with a hardcoded static
  fallback retained for offline boots.
- The `/model` slash command lists available models (name, id, provider,
  context window) across the TUI, web chat, and channel surfaces, with an
  optional `/model <filter>` substring filter.

### Tools, skills, and memory

- MCP-native tools and 37 bundled skills (coding, GitHub, cron, pptx/docx/xlsx/pdf,
  summaries, tmux, weather, and more) that load only when a task needs them.
  AgentOS can consume other MCP servers and expose itself as one
  (`agentos mcp-server run`, `mcp` extra).
- Persistent local memory: a `MEMORY.md` file plus dated Markdown notes,
  searchable by keyword (SQLite FTS) or meaning (`sqlite-vec`). Semantic recall
  runs on-device via a bundled BGE ONNX embedding model
  (`src/agentos/memory/models/bge_onnx/`), or can defer to OpenAI / Ollama.
- Built-in web search (Brave or DuckDuckGo) with SSRF-safe page fetching,
  document generation (PPTX/DOCX/PDF), image generation, and text-to-speech.

### Security and operations

- Layered security sandbox with three levels (Standard, Strict, Locked):
  Bubblewrap on Linux, `sandbox-exec` (Seatbelt) on macOS. Repeated denials
  auto-pause the agent; blocked output and tool results are sanitized so they
  cannot steer the model.
- Operator controls: human approval for risky tool calls, per-turn and
  per-session token/cost accounting (`agentos cost`), and diagnostics from both
  the CLI and Web UI (`agentos doctor`, the Web UI Health page).
- A `SchedulerEngine` with a built-in cron reader runs jobs via `agentos cron`.
- Config is auto-discovered (`AGENTOS_GATEWAY_CONFIG_PATH` → `./agentos.toml`
  → `~/.agentos/config.toml` → built-in defaults); environment-variable secrets
  always win over file values.
- One-way import from OpenClaw (`~/.openclaw`) and Hermes Agent (`~/.hermes`)
  via `agentos migrate`, with dry-run reports before applying.

### Brand and contribution

- Brand identity: the AgentOS wordmark and molecule mark.
- Plain pull-request contribution flow targeting `main`; relicensed to MIT.
