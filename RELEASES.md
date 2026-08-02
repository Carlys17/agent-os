# AgentOS Releases

| Version | Tag | Date | Notes |
|---|---|---|---|
| 2026.8.2.post1 | v2026.8.2.post1 | 2026-08-02 | A packaging fix for the 2026.8.2 release. The wheel guard allowed markdown only at a bundled skill's `SKILL.md` plus two force-included pptx references, so `senior-unilp-manager`'s `assets/v4-reference.md` read as a forbidden entry and the tagged Windows release job failed for v2026.8.2 after the tag was already pushed — while a wheel that did build shipped `SKILL.md` links pointing at a file stripped from disk. `agentos/skills/bundled/<skill>/assets/**` is now allowed (`references/` and stray top-level markdown stay forbidden) and a real-tree test over the bundled skills fails PR CI instead of the tagged release job. Cron prompt safety no longer rejects Unicode combining marks — Vietnamese and other scripts that need them pass again, while genuinely invisible marks stay blocked. |
| 2026.8.2 | v2026.8.2 | 2026-08-02 | A harness-reliability and skills release. `edit_file` no longer fails on text that differs from the file only in formatting — it falls back through indentation, whitespace, escaped-newline, smart-quote and block-similarity strategies and names the one that matched, while still refusing ambiguous matches. The progress watchdog now catches repeated *successful* calls, not just failures, so an agent re-reading the same file stops looking like progress. A turn that edits code and answers "done" without running anything is noticed and warned, and the system prompt names the developer tools that actually exist on the machine (`[prompt] env_probe_enabled`). Side-task LLM calls (document analysis, image description) run through one accounted auxiliary client configured at `[auxiliary]`, so their cost shows up in `agentos cost`. Streaming replies survive gateways that send `choices`/`tool_calls` as explicit `null`, MCP tool schemas are sanitized at discovery so one malformed tool cannot fail a whole request, and provider error bodies are bounded and summarised instead of flowing whole into context. New bundled skill `senior-unilp-manager` reads and manages Uniswap v4 liquidity on Base and Robinhood Chain over stdlib-only JSON-RPC with a two-process `PLAN_HASH` confirm gate — now binding every calldata-affecting flag — and can find and mint into hook-less pools. `skill_view` resolves `{baseDir}`, a cron job may opt in to running shell-based skills (#184), and the Skills page groups Partner / AgentOS Normal / AgentOS Crypto skills with clearer status buckets. |
| 2026.7.31 | v2026.7.31 | 2026-07-31 | A security release for skills that call authenticated APIs. The outbound guard matched credential-ish *names*, so `http_request` refused every `Authorization` header and `exec_command` refused `{"sellToken": …}` and `grep "token: "` — while a real key pasted inline passed through; the guard now matches credential **values** and leaves names alone, the shell check runs only on commands that can reach the network, and a skill declaring `metadata.requires.env` gets those names forwarded into the sandbox so the value never enters the transcript (#165, #167). Command output is scanned for credentials before it reaches the model, `AGENTOS_GATEWAY_TOKEN` no longer leaks into child processes, and `http_request` refuses cloud metadata endpoints. Router tier defaults move up a generation across all gateway profiles — C1 to `gpt-5.6-luna`, C3 to `claude-opus-5`, with `claude-opus-5` registered for its 1M context window and real pricing (#169) — and the Pilot Router docs describe the C0–C3 tiers (#170). |
| 2026.7.30 | v2026.7.30 | 2026-07-30 | A skills release. The agent can now tell which of its installed skills applies to a request: the prompt budget shortens descriptions to the longest length that fits instead of dropping every description at a cliff, names-only mode points at `skill_list` rather than one `skill_view` per skill, the block moves into the cacheable system prompt, and cron turns get `skill_view`/`skill_list` (#159). `skill_view` on a skill that is not installed now says the lookup worked and offers `skill_search_community` instead of reading as a broken tool (#162), and a skill over the new `[skills].max_skill_view_chars` (default 10 000) returns its opening sections plus an index instead of every byte — 43% fewer characters across a real install, 80–87% on the largest (#163). Capminal Skills are browsable and installable as a partner source (#144), runtime dependencies carry upper bounds (#153), and the Web UI skill grid and Installed chip are fixed (#135, #161, #121). |
| 2026.7.29 | v2026.7.29 | 2026-07-29 | Bankr skills published from bankr.bot — the ones under an author's wallet address rather than in `BankrBot/skills` — can be browsed and installed like any other hub skill; the `SKILL.md` is synthesized from the inline JSON payload, the skill is credited to its author instead of inheriting Bankr's brand, and only allowlisted skills install through the Bankr source (#150). `SECURITY.md` states that audit reports belong in the private advisory form rather than a PR, that there is no bug bounty program, and that researchers are credited in the release notes of the fix (#154). |
| 2026.7.28 | v2026.7.28 | 2026-07-28 | Web UI polish: `Cmd/Ctrl+Shift+O` starts a new chat from anywhere in the console, with the platform-appropriate hint on the New Chat tooltip (#131); the settings screen is called **Agent Setup** everywhere — route title, sidebar, heading, browser tab, and docs (#125). |
| 2026.7.27 | v2026.7.27 | 2026-07-27 | Environment variables are managed from AgentOS instead of by hand-editing `~/.agentos/.env` — an **Environment** screen, `agentos env list\|get\|set\|unset`, `env.*` RPC, a **Set &lt;VAR&gt;** action in the Skills dialog, and detection of credentials that already exist such as `gh auth` (#122, #127, #129). Every surface now gives the same answer about a skill: whether it is offered, and which of six reasons explains why not; Installed cards group by provenance, skills carry allowlisted publishers, and `skills.max_skills_prompt_chars` defaults to 24000 with the filesystem path dropped from the skills block (#130, #132). Curated memory stops fabricating profile facts and the background review wakes as designed (#128). **Removed:** the session-flush subsystem and the `memory.flush_*` / `memory.repair_*` config keys (#124). |
| 2026.7.26 | v2026.7.26 | 2026-07-26 | **Breaking:** channel roles and scoped tokens replaced by Control/Channel pairing surfaces with durable Telegram pairing and grant revalidation (#104); curated-memory durability pass — atomic turn captures, Windows write locks, non-destructive `MEMORY.md` migration, surfaced unreadable files (#106–#114); periodic memory-review nudge at `[memory.nudge]` (#108); non-destructive `/new` and `/reset` when flush is unavailable (#102, #117); OpenCAP LLM gateway provider (#63); Slack/Discord/Telegram slash-command and interaction fixes (#93–#101); Dream consolidation and the memory repair service removed (#116, #118). |
| 2026.7.25 | v2026.7.25 | 2026-07-25 | React Control UI is now the only verified production interface with settings/configuration transaction safety and hardened CSP; retired channel adapters and legacy UI removed; frontend settings, Bankr icons, session reset, collapsed sidebar, CLI onboarding prompt, and default `openai/gpt-5.6-luna` model fixes. |
| 2026.7.23 | v2026.7.23 | 2026-07-23 | Mouse drag selection and copy in the full-screen `agentos chat` transcript (#76); turn-lifetime waiting indicator and markdown streaming fixes that remove ghost panels in Windows PowerShell; reasoning-model think-block rendering; Telegram keeps its native command menu across gateway restarts (#74). |
| 2026.7.22.post1 | v2026.7.22.post1 | 2026-07-22 | `agentos chat` full-screen transcript mouse wheel scrolling is responsive on the first tick (larger wheel step plus follow-release compensation) (#69). |
| 2026.7.22 | v2026.7.22 | 2026-07-22 | Native slash-command menus for Telegram, Slack, and Discord (#45); Ollama multi-turn tool-call history fixes and a `tools.enabled = false` plain-text fallback mode (#44); channel slash commands render their RPC results instead of a generic acknowledgement; Telegram delivery retries transient connection failures; `agentos chat` input frame supports multiline input (#62). |
| 2026.7.20 | v2026.7.20 | 2026-07-20 | `agentos chat` CLI UX pass (#46/#47): assistant speaker label defaults to `agentos` and is configurable via `AGENTOS_ASSISTANT_LABEL`; session title in the bottom toolbar and startup panel; `/c0`–`/c3` and `/auto` router-tier holds on both CLI surfaces; framed input box; full-screen chat transcript pane now the default. |
| 2026.7.19.post1 | v2026.7.19.post1 | 2026-07-19 | Remove legacy v4_phase3 router engine and model bundle; rename to Pilot Router; sync router docs |
| 2026.7.19 | v2026.7.19 | 2026-07-19 | AgentOS Pilot (`pilot-v1`) is now the default router strategy with force-migration off `v4_phase3` (#26, #36); bundled `agentos` self-operation skill (#37); Bankr browse source limited to two skills with Update button, emoji avatar, brand-glyph logo, and null-description crash fix (#39). |
| 2026.7.18.post1 | v2026.7.18.post1 | 2026-07-18 | Release-hygiene re-cut: propagate the 2026.7.18 version across `uv.lock`, consistency/install tests, `RELEASES.md`, `CHANGELOG.md`, README install examples, and `install.sh`/`install.ps1`. No runtime code changes. |
| 2026.7.18 | v2026.7.18 | 2026-07-18 | Gateway: interactive auth provisioning on public bind, host/port CLI-only (#25); browser-threat hardening on loopback binds — CSWSH/DNS-rebinding guards (#24); rebrand to "Token-Efficient AI agent with on-device Pilot Router" |
| 2026.7.17.post1 | v2026.7.17.post1 | 2026-07-17 | `session_status` tool fix: resolve the calling session from the tool context instead of a `SessionManager` method that never existed |
| 2026.7.17 | v2026.7.17 | 2026-07-17 | Memory provider layer (mem0) + curated stores; v4_phase3 router bundle restored; Web UI transcript redesign; embedding-download redirect fix |
| 2026.7.15.post1 | v2026.7.15.post1 | 2026-07-15 | Partner-catalog skills system + Robinhood RWA address lookup skill (Bankr hub) |
| 2026.7.15 | v2026.7.15 | 2026-07-15 | Relicense to Apache-2.0 with `NOTICE` + OpenSquilla attribution; wheels ship license files |
| 2026.7.14.post1 | v2026.7.14.post1 | 2026-07-14 | PyPI distribution rename to `use-agent-os`; first PyPI release |
| 2026.7.14 | v2026.7.14 | 2026-07-14 | Release |
| 0.0.1 | v0.0.1 | 2026-07-05 | AgentOS baseline release |

Versions follow CalVer (`YYYY.M.D`). PEP 440 normalizes wheel filenames and drops
leading zeros, so tags must use the same non-padded form — tag `v2026.7.15`, not
`v2026.07.15`, or the wheel filename (`use_agent_os-2026.7.15-py3-none-any.whl`) will
not match the tag and the release smoke check fails.

Preview releases publish only versioned assets:

- `AgentOS-<version>-windows-x64-py312-recommended-portable.zip`
- `use_agent_os-<version>-py3-none-any.whl`
- `SHA256SUMS`

Non-preview releases additionally publish a version-independent alias for the
Windows portable zip `/releases/latest/download/` URL:

- `AgentOS-windows-x64-portable.zip`

GitHub source archives remain available for code review and developer
reference; source installs should use `git clone` plus Git LFS. Public
wheelhouse zips, macOS portable zips, and Linux portable zips are intentionally
not published for the 0.0.x line. macOS and Linux users install the same wheel
through the versioned `uv tool install` command documented in the README.
Python wheel filenames must remain versioned because installers validate the
version segment inside the wheel filename.

Preview releases are GitHub pre-releases. Their README install commands must
use tag-pinned URLs such as:

- `https://github.com/use-agent-os/agent-os/releases/download/v0.0.1rc1/AgentOS-0.0.1rc1-windows-x64-py312-recommended-portable.zip`
- `https://github.com/use-agent-os/agent-os/releases/download/v0.0.1rc1/use_agent_os-0.0.1rc1-py3-none-any.whl`

0.0.1 install commands use versioned wheel URLs because Python installers
validate wheel filenames. The Windows portable zip may use the
`/releases/latest/download/` alias after the non-pre-release GitHub Release
exists. Fully pinned URLs remain available:

- `https://github.com/use-agent-os/agent-os/releases/download/v0.0.1/AgentOS-0.0.1-windows-x64-py312-recommended-portable.zip`
- `https://github.com/use-agent-os/agent-os/releases/download/v0.0.1/use_agent_os-0.0.1-py3-none-any.whl`

## Release SOP

1. Verify `git status` is clean.
2. Update `CHANGELOG.md`: move entries from `[Unreleased]` to the release section; reopen empty `[Unreleased]`.
3. Bump `pyproject.toml` and `uv.lock` to the release version.
4. `git tag -a v0.0.1 -m "AgentOS 0.0.1"`
5. `git push origin v0.0.1` (this triggers `.github/workflows/wheelhouse-release.yml`)
6. Wait for the Windows release workflow → review the draft GitHub Release.
   For non-preview releases, confirm it contains versioned assets, latest
   aliases, `SHA256SUMS`, plus GitHub's generated source archives before
   publishing.
7. Confirm the draft GitHub Release is not marked as a pre-release.
8. Publish the GitHub Release, then run the post-publish tag URL checks:

   ```sh
   curl --fail --head --location https://github.com/use-agent-os/agent-os/releases/download/v0.0.1/AgentOS-0.0.1-windows-x64-py312-recommended-portable.zip
   curl --fail --head --location https://github.com/use-agent-os/agent-os/releases/download/v0.0.1/use_agent_os-0.0.1-py3-none-any.whl
   ```

9. Run the post-publish latest URL check:

   ```sh
   curl --fail --head --location https://github.com/use-agent-os/agent-os/releases/latest/download/AgentOS-windows-x64-portable.zip
   ```

10. For subsequent previews: bump `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, and the tag to the next preview version, for example `0.0.2rc1` / `v0.0.2rc1`. Preview GitHub Releases must be marked as pre-releases and should use tag-pinned README URLs until the next non-preview release exists.

## GitHub-only release checks

These checks cannot be fully proven by local artifact generation:

- The tag exists on GitHub and matches `pyproject.toml`.
- The release workflow can fetch hydrated Git LFS router assets.
- Preview GitHub Releases contain the versioned assets and `SHA256SUMS` after
  `gh release upload --clobber`.
- Non-preview GitHub Releases contain the versioned assets, Windows latest alias, and
  `SHA256SUMS` after `gh release upload --clobber`.
- After a non-preview GitHub Release is published, the latest Windows portable
  URL resolves: `.../releases/latest/download/AgentOS-windows-x64-portable.zip`.
- After a preview GitHub Release is published, the tag-pinned release asset URLs
  resolve.
- Windows browser downloads may carry Mark-of-the-Web; SmartScreen,
  Smart App Control, enterprise policy, and unsigned binary reputation must be
  checked on a real Windows machine.

## Why preview package versions use rc

Release zips are distributed as built artifacts, so the package filename,
manifest, zip name, and tag should describe the same preview build. PEP 440
accepts `0.0.1rc1`, while the public GitHub Release title can use the friendlier
name "AgentOS 0.0.1 Preview 1".
