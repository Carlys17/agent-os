"""Invariants for the supported channel install contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
UV_LOCK = Path(__file__).resolve().parents[2] / "uv.lock"


@pytest.fixture(scope="module")
def project_table() -> dict:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]


@pytest.fixture(scope="module")
def lock_package() -> dict:
    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    return next(package for package in data["package"] if package["name"] == "use-agent-os")


@pytest.fixture(scope="module")
def locked_versions() -> dict[str, str]:
    """Every version uv.lock resolves, keyed by package name.

    The bounds policy is expressed relative to what we actually lock and test, so the
    expected cap is computed from here rather than restated in the test.
    """

    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    return {package["name"]: package["version"] for package in data["package"]}


def _dep_name(spec: str) -> str:
    """Extract the canonical (lowercased) package name from one PEP 508 spec."""

    head = spec.strip()
    for sep in ("[", " ", ";", "=", ">", "<", "~", "!"):
        head = head.split(sep, 1)[0]
    return head.lower()


def _dep_names(specs: list[str]) -> set[str]:
    """Extract canonical (lowercased) package names from a list of PEP 508 specs."""

    return {name for spec in specs if (name := _dep_name(spec))}


# Dependencies that ship to consumers without an upper bound, on purpose (#153).
# Two classes only, and both are >=1.0 — see `test_no_zerover_dependency_is_exempt`:
#   - CalVer projects, where a cap expires by the calendar rather than by a break.
#   - packages whose surface we call has been stable for years, where a cap buys
#     nothing and costs co-installability.
# Anything else needs a cap. This list is checked in both directions: adding a cap
# to something listed here fails until the name is removed.
INTENTIONALLY_UNCAPPED = {
    # CalVer — the version number tracks the year, not the API.
    "structlog",
    "html2text",
    # Stable, narrow surface: `safe_load`, `Template.render`, a TTLCache, a `dumps`.
    "brotli",
    "jinja2",
    "pyyaml",
    "cachetools",
    "tomli-w",
}

# `dev` is contributor tooling pinned by uv.lock, not something a downstream
# `pip install use-agent-os[...]` resolves fresh. Every other extra is a consumer
# surface and is held to the same bar as the base list.
UNBOUNDED_EXTRAS = {"dev"}


def _consumer_specs(project_table: dict) -> list[str]:
    """Every spec a downstream `pip install` resolves — base plus non-dev extras."""

    specs = list(project_table["dependencies"])
    for extra, extra_specs in project_table.get("optional-dependencies", {}).items():
        if extra not in UNBOUNDED_EXTRAS:
            specs.extend(extra_specs)
    return specs


def _release_series(version: str) -> tuple[int, ...]:
    """The (major, minor) a version belongs to, as leading integers."""

    parts = tuple(int(part) for part in re.findall(r"\d+", version)[:2])
    return parts + (0,) * (2 - len(parts))


def _expected_cap(locked: str) -> tuple[int, int]:
    """The first release upstream is free to break in, given what uv.lock pins.

    Semver reserves breaking changes for the major bump — except below 1.0, where the
    minor is the breaking unit. `typer<1.0` against a locked 0.24.1 is therefore not a
    cap at all: it waves through every 0.x release upstream cares to make.
    """

    major, minor = _release_series(locked)
    return (0, minor + 1) if major == 0 else (major + 1, 0)


def _declared_cap(spec: str) -> tuple[int, int] | None:
    """The `<` bound in a PEP 508 spec, as (major, minor)."""

    # Split the environment marker off first: a marker like `python_version < "3.13"`
    # carries a `<` that says nothing about the version bound.
    match = re.search(r"<\s*([0-9][0-9.]*)", spec.split(";", 1)[0])
    if match is None:
        return None
    major, minor = _release_series(match.group(1))
    return (major, minor)


def test_declared_dependencies_carry_upper_bounds(project_table: dict) -> None:
    """Every consumer-facing dependency is capped, or explicitly exempt.

    `uv.lock` makes contributor and CI installs reproducible, but a downstream
    `pip install use-agent-os` resolves fresh against PyPI and takes whatever each
    package published most recently — including a breaking release published after
    ours. Without a cap, a dependency we never touched can break new installs, and the
    resulting bug report has no resolvable dependency set to reproduce from.

    The policy lives above `dependencies` in pyproject.toml and in CONTRIBUTING.md:
    cap at the next breaking release, with a short exemption list rather than a blanket
    cap on all of them, because capping uniformly makes AgentOS painful to co-install.
    """

    uncapped = {
        _dep_name(spec) for spec in _consumer_specs(project_table) if _declared_cap(spec) is None
    }

    missing = sorted(uncapped - INTENTIONALLY_UNCAPPED)
    assert not missing, (
        "these ship to `pip install` consumers with no upper bound — cap them at the "
        "next breaking release above what uv.lock pins, or add them to "
        f"INTENTIONALLY_UNCAPPED with a reason: {missing}"
    )

    now_capped = sorted(INTENTIONALLY_UNCAPPED - uncapped)
    assert not now_capped, (
        f"these are capped now — drop them from INTENTIONALLY_UNCAPPED: {now_capped}"
    )


def test_upper_bounds_sit_at_the_next_breaking_release(
    project_table: dict, locked_versions: dict[str, str]
) -> None:
    """A cap must land on the next release upstream may break in, not further out.

    Checking only that *a* `<` exists lets the bound drift off the policy silently: a
    0.x dependency capped at `<1.0` reads as bounded and is not, and a `<70.0` against a
    locked 68.1 lets an untested 69.0 straight into a fresh install. Both had happened
    here before this test existed. The boundary is recomputed from uv.lock rather than
    hardcoded, so bumping a locked version tells you to move its cap.
    """

    drifted = []
    for spec in _consumer_specs(project_table):
        name = _dep_name(spec)
        declared = _declared_cap(spec)
        if declared is None or name not in locked_versions:
            continue
        expected = _expected_cap(locked_versions[name])
        if declared != expected:
            drifted.append(
                f"{name}: locked {locked_versions[name]}, capped <{declared[0]}.{declared[1]}, "
                f"expected <{expected[0]}.{expected[1]}"
            )

    assert not drifted, (
        "these caps do not sit at the next breaking release — a 0.x dependency caps at "
        "the next minor, everything else at the next major:\n  " + "\n  ".join(sorted(drifted))
    )


def test_no_zerover_dependency_is_exempt(locked_versions: dict[str, str]) -> None:
    """Exemptions are for >=1.0 packages only.

    The exemption rationales — CalVer, or a surface stable for years — are claims about
    projects that have committed to a stable line. A package still numbered below 1.0
    has not, whatever its actual release cadence, so it does not get to skip the cap.
    """

    zerover = sorted(
        f"{name} ({locked_versions[name]})"
        for name in INTENTIONALLY_UNCAPPED
        if name in locked_versions and _release_series(locked_versions[name])[0] == 0
    )
    assert not zerover, (
        "these are exempt from capping but are still 0.x, where the minor is the "
        f"breaking unit — cap them at the next minor instead: {zerover}"
    )


def test_supported_channel_sdk_is_in_base(project_table: dict) -> None:
    """Telegram imports its vendor SDK and must keep it in the base install."""

    base = _dep_names(project_table["dependencies"])
    assert "python-telegram-bot" in base
    assert not {"dingtalk-stream", "qq-botpy", "cryptography"} & base


def test_mcp_sdk_is_a_base_dependency(project_table: dict) -> None:
    """The built-in MCP UI and server must work without an install extra."""

    base = _dep_names(project_table["dependencies"])
    extras = project_table.get("optional-dependencies", {})

    assert "mcp" in base
    assert "mcp" not in extras


def test_no_dead_extras(project_table: dict) -> None:
    """Retired and non-public adapters must not expose install extras."""

    extras = project_table.get("optional-dependencies", {})
    assert not {"dingtalk", "matrix", "matrix-e2e", "msteams", "qq", "wecom"} & set(extras)


def test_base_channel_extras_are_not_exposed_as_noop_aliases(
    project_table: dict,
) -> None:
    """Base-install channels must not be exposed as no-op extras."""

    extras = project_table.get("optional-dependencies", {})
    for name in ("discord", "slack", "telegram"):
        assert name not in extras, f"{name} is installed from base; do not expose a no-op extra"


def test_lockfile_does_not_advertise_removed_base_channel_extras(
    lock_package: dict,
) -> None:
    """uv.lock metadata must match the package install contract."""

    provides_extras = set(lock_package.get("provides-extras", []))
    assert not {
        "dingtalk",
        "discord",
        "matrix",
        "matrix-e2e",
        "qq",
        "slack",
        "telegram",
        "wecom",
    } & provides_extras


def test_no_duplicate_ml_extra(project_table: dict) -> None:
    """``recommended`` and ``model-router`` historically overlapped — only one survives."""

    extras = project_table.get("optional-dependencies", {})
    has_recommended = "recommended" in extras
    has_model_router = "model-router" in extras
    assert has_recommended, "recommended extra must exist (router users opt in here)"
    assert not has_model_router, (
        "model-router extra duplicates recommended — collapse into one"
    )


def test_alpha_classifier_present(project_table: dict) -> None:
    """0.1.0 stays pre-stable — the classifier must reflect that."""

    classifiers = project_table.get("classifiers", [])
    assert "Development Status :: 3 - Alpha" in classifiers, (
        "Alpha classifier signals to PyPI/uv that this is pre-stable"
    )


def test_readme_points_at_user_facing_file(project_table: dict) -> None:
    """``readme`` must be the user-facing README, not the legacy portable view."""

    assert project_table["readme"] == "README.md", (
        "readme should point at the canonical README.md after the 0.1.0 refactor"
    )


# Bundled skills whose SKILL.md already links to a `references/` file the wheel drops.
# Pre-existing at the time this check was written; listed rather than silently tolerated
# so the count can only go down. Fixing one means moving its files into `assets/` and
# repointing SKILL.md.
KNOWN_STRANDED_REFERENCES = {
    "src/agentos/skills/bundled/deep-research/references/methodology.md",
    "src/agentos/skills/bundled/deep-research/references/sources.md",
    "src/agentos/skills/bundled/docx/references/python_docx.md",
    "src/agentos/skills/bundled/pdf-toolkit/references/reportlab.md",
    "src/agentos/skills/bundled/seedance-2-prompt/references/camera-and-styles.md",
    "src/agentos/skills/bundled/seedance-2-prompt/references/modes-and-recipes.md",
    "src/agentos/skills/bundled/seedance-2-prompt/references/recipes.md",
    "src/agentos/skills/bundled/xlsx/references/openpyxl.md",
}


def test_skill_docs_do_not_link_to_files_the_wheel_strips() -> None:
    """A SKILL.md must not point at a `references/` file that never reaches an install.

    `[tool.hatch.build.targets.wheel].exclude` drops
    `src/agentos/skills/bundled/**/references/*.md` wholesale, and `force-include` adds
    back exactly two `pptx` files. A skill that puts load-bearing documentation there
    ships instructions pointing at a file that is not on disk, and nothing fails at build
    time to say so. Put such files in `assets/`, which is shipped.
    """

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    forced = set(data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"])
    bundled = PYPROJECT.parent / "src" / "agentos" / "skills" / "bundled"

    stranded = set()
    for path in bundled.glob("*/references/*.md"):
        # as_posix, not str: pyproject spells these paths with forward slashes, and on
        # Windows str() would emit backslashes that match neither `forced` nor the
        # allowlist below — every file would look newly stranded.
        rel = path.relative_to(PYPROJECT.parent).as_posix()
        if rel in forced:
            continue
        skill_md = (path.parents[1] / "SKILL.md").read_text(encoding="utf-8")
        if f"references/{path.name}" in skill_md:
            stranded.add(rel)

    new = sorted(stranded - KNOWN_STRANDED_REFERENCES)
    assert not new, (
        "these files are excluded from the wheel but referenced by their SKILL.md — "
        f"move them to the skill's assets/ directory: {new}"
    )
    fixed = sorted(KNOWN_STRANDED_REFERENCES - stranded)
    assert not fixed, f"these are fixed — drop them from KNOWN_STRANDED_REFERENCES: {fixed}"
