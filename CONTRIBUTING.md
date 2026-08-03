# Contributing

Thanks for improving AgentOS. Keep pull requests small, focused, and covered
by tests that outside contributors can run without private access.

## Issues

Before opening a new issue, search the existing open and closed issues. If one
already covers your report, comment there instead of opening a duplicate.

Open an issue before opening a pull request for a bug fix or a new feature.
Maintainers confirm the change is needed and can assign the issue to you.

Give every issue the labels that match it: one `type:` label, the relevant
`area:` label, and a `priority:` label when you can judge it. List the labels
this repository defines with `gh label list` (or the Labels page on GitHub)
and pick from those rather than inventing new ones.

To claim an issue, comment on it. A maintainer will assign it to you and add
`status: claimed`. Check the assignee before you start work — do not fix an
issue that is already assigned to someone else, because it duplicates their
effort.

If an assigned contributor posts no progress within three days, maintainers
may unassign the issue so someone else can take it over.

## Pull Requests

Open pull requests against `main`. Every pull request must link its issue in
the description with a GitHub keyword: `Fixes #123` or `Closes #123` when the
pull request fully resolves the issue, or `Refs #123` when it does not.

A pull request that closes an issue should solve that issue completely. If it
covers only part of the issue, use `Refs #123` and say in the description what
still remains.

You do not have to wait to be assigned. Opening a pull request that links the
issue is enough to claim the work — just check the assignee first so you do not
duplicate someone else's effort.

When a squash or rebase collapses commits from several people, keep the final
commit attributable with `Co-authored-by:` trailers for every contributor
whose work is included.

## Default Checks

Install development dependencies:

```sh
uv sync --extra dev --extra recommended
```

Run the quality gate before opening a pull request:

```sh
python scripts/build_control_ui.py build
npm --prefix frontend run check
uv run ruff check src tests
uv run mypy src/agentos --show-error-codes
uv run pytest -q
uv build --wheel
```

Node.js 22 or newer is required for source installs and release-artifact
builds. Python-only inner-loop tests do not need Node, but the final wheel gate
does because the wheel must contain a freshly verified Control UI bundle.

Default tests must be offline, deterministic, credential-free, and safe for
forks. Do not add network, provider, browser, or channel requirements to the
default pull request path.

## Test Expectations

Add or update public regression tests for behavior changes and bug fixes.
Prefer focused unit or integration tests unless the behavior crosses the
gateway, browser UI, provider, or channel boundary. Live provider, browser,
and channel smoke tests are maintainer-only opt-in workflows
(`Live Release E2E` and `LLM E2E`).

## Private Materials

Private test suites, real provider transcripts, real channel identifiers,
local paths, credentials, and AI session artifacts must not be committed.
Local maintainer-only files may live under `tests/_private/`; it is excluded
from the public tree and default pytest collection.

## Third-Party Origins

Declare any third-party origin in the pull request (`none` if there is none):
`inspired-by`, `adapted/ported`, `vendored`, `direct dependency`, or
`modified upstream`. For adapted, vendored, or modified upstream material,
include the upstream URL, license, copyright notice, and any required changes
to `THIRD_PARTY_NOTICES.md` in the same pull request.

Permissive licenses (Apache-2.0, MIT, BSD, ISC) are usually acceptable. GPL,
AGPL, LGPL, SSPL, source-available, or unclear licenses require explicit
maintainer approval before merge.

## Security Reports

Do not include vulnerability details, exploit steps, credentials, or provider
tokens in public issues. Use the process in `SECURITY.md` for suspected
vulnerabilities.

## Community Standards

Keep discussion technical, specific, and respectful. Expected conduct is
documented in `CODE_OF_CONDUCT.md`.
