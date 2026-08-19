from __future__ import annotations

from agentos.skills.outline import (
    always_sections,
    find_section,
    head_sections,
    indexable,
    parse_sections,
    render_outline,
    render_pinned,
)


def _body(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_headings_inside_fenced_code_are_not_sections() -> None:
    """A skill that shows markdown or a shell transcript is full of '#' lines.

    Reading those as headings invents sections that section= cannot return,
    and moves the head's cut point into the middle of a code block.
    """
    body = _body(
        "# Guide",
        "",
        "```sh",
        "# install it first",
        "brew install thing",
        "```",
        "",
        "## Real section",
        "text",
    )

    titles = [s.title for s in parse_sections(body)]

    assert titles == ["Guide", "Real section"]


def test_a_nested_fence_does_not_close_the_outer_one() -> None:
    """Skills that document markdown wrap a ``` block inside a ```` one."""
    body = _body(
        "# Guide",
        "",
        "````markdown",
        "```py",
        "# not a heading",
        "```",
        "## also not a heading",
        "````",
        "",
        "## Real section",
    )

    titles = [s.title for s in parse_sections(body)]

    assert titles == ["Guide", "Real section"]


def test_a_section_owns_its_subsections() -> None:
    body = _body(
        "## Parent",
        "intro",
        "### Child A",
        "a",
        "### Child B",
        "b",
        "## Next",
        "n",
    )

    sections = {s.title: s for s in parse_sections(body)}
    parent = sections["Parent"]

    assert body[parent.start : parent.end].strip().endswith("b")
    assert "## Next" not in body[parent.start : parent.end]


def test_a_title_heading_that_owns_the_whole_body_is_not_the_index() -> None:
    """Large skills open with one '# Title' spanning every byte.

    Indexing that level yields a single entry the size of the whole skill, and
    a head built from it is empty — which is what shipped before this test.
    """
    body = _body(
        "# Bankr",
        "intro paragraph",
        "## Getting started",
        "x" * 400,
        "## Commands",
        "y" * 400,
        "## Troubleshooting",
        "z" * 400,
    )

    entries = [s.title for s in indexable(parse_sections(body))]

    assert entries == ["Getting started", "Commands", "Troubleshooting"]


def test_the_head_ends_on_a_heading_and_is_not_empty() -> None:
    body = _body(
        "# Title",
        "intro",
        "## One",
        "x" * 300,
        "## Two",
        "y" * 300,
        "## Three",
        "z" * 5_000,
    )
    sections = parse_sections(body)

    head, shown_through = head_sections(body, sections, 1_000)

    assert head.startswith("# Title")
    assert "## One" in head
    assert "## Three" not in head
    assert body[shown_through:].lstrip().startswith("#")


def test_a_deep_index_collapses_instead_of_becoming_the_problem() -> None:
    """Two levels is cheap until a skill has ninety headings two levels down."""
    lines = ["# Title", "intro"]
    for parent in range(12):
        lines += [f"## Parent {parent}", "text"]
        for child in range(6):
            lines += [f"### Child {parent}.{child}", "text"]
    sections = parse_sections(_body(*lines))

    entries = indexable(sections)

    assert len(entries) == 12
    assert all(s.title.startswith("Parent") for s in entries)
    # Collapsing costs no reach — every heading is still addressable.
    assert find_section(sections, "Child 3.2") is not None


def test_a_section_is_found_by_title_case_and_path() -> None:
    body = _body(
        "## Setup",
        "s",
        "### Notes",
        "under setup",
        "## Usage",
        "u",
        "### Notes",
        "under usage",
    )
    sections = parse_sections(body)

    assert find_section(sections, "  usage  ").title == "Usage"  # type: ignore[union-attr]
    assert find_section(sections, "Setup > Notes").ancestors == ("Setup",)  # type: ignore[union-attr]


def test_an_ambiguous_title_returns_the_candidates_rather_than_a_guess() -> None:
    body = _body("## Setup", "s", "### Notes", "a", "## Usage", "u", "### Notes", "b")
    sections = parse_sections(body)

    match = find_section(sections, "Notes")

    assert isinstance(match, list)
    assert {s.path for s in match} == {"Setup > Notes", "Usage > Notes"}


def test_an_unknown_section_is_not_matched() -> None:
    sections = parse_sections(_body("## Setup", "s"))

    assert find_section(sections, "nothing like this") is None


def test_the_index_marks_what_the_head_already_returned() -> None:
    body = _body("# T", "i", "## One", "x" * 100, "## Two", "y" * 100)
    sections = parse_sections(body)
    _head, shown_through = head_sections(body, sections, 130)

    rendered = render_outline(sections, shown_through=shown_through, skill_name="demo")

    assert "One — " in rendered
    assert "(shown above)" in rendered
    assert 'skill_view(name="demo", section="<title>")' in rendered


def test_a_body_without_headings_has_nothing_to_index() -> None:
    assert parse_sections("just prose, no headings\n") == []
    assert indexable([]) == []


def test_a_marked_section_is_pinned_wherever_it_sits() -> None:
    """The rule a skill cannot afford to have truncated.

    Section order otherwise decides what a model reads, so a rule added to a
    large skill lands in the indexed tail and is never seen unless the model
    thinks to ask for it.
    """
    body = _body(
        "# T",
        "intro",
        "## One",
        "x" * 400,
        "<!-- always -->",
        "## Rules",
        "never do that",
    )
    sections = parse_sections(body)

    pinned = always_sections(body, sections)

    assert [s.title for s in pinned] == ["Rules"]


def test_an_unmarked_skill_pins_nothing() -> None:
    body = _body("# T", "i", "## One", "x" * 400, "## Two", "y" * 400)

    assert always_sections(body, parse_sections(body)) == []


def test_the_marker_is_read_through_blank_lines() -> None:
    body = _body("# T", "i", "<!-- always -->", "", "## Rules", "r")

    assert [s.title for s in always_sections(body, parse_sections(body))] == ["Rules"]


def test_a_marker_that_is_not_the_nearest_line_pins_nothing() -> None:
    """A marker with prose between it and the heading marks nothing.

    Otherwise the word appearing anywhere above a heading would pin it, and a
    skill discussing the marker would pin sections it never meant to.
    """
    body = _body("# T", "<!-- always -->", "some prose", "## Rules", "r")

    assert always_sections(body, parse_sections(body)) == []


def test_a_marker_inside_a_fence_pins_nothing() -> None:
    """A skill documenting the marker shows it in a code block."""
    body = _body(
        "# T",
        "```md",
        "<!-- always -->",
        "## Not a section",
        "```",
        "",
        "## Real",
        "r",
    )

    assert always_sections(body, parse_sections(body)) == []


def test_the_index_marks_a_pinned_section_as_already_shown() -> None:
    body = _body("# T", "i", "## One", "x" * 200, "<!-- always -->", "## Rules", "r")
    sections = parse_sections(body)
    pinned = always_sections(body, sections)

    rendered = render_outline(
        sections,
        shown_through=0,
        skill_name="demo",
        also_shown=pinned,
    )

    lines = [line for line in rendered.splitlines() if "Rules" in line]
    assert lines and lines[0].endswith("(shown above)")


def test_pinned_text_is_rendered_under_a_heading_that_says_why() -> None:
    body = _body("# T", "i", "<!-- always -->", "## Rules", "never do that")
    sections = parse_sections(body)

    rendered = render_pinned(body, always_sections(body, sections))

    assert "## Rules" in rendered
    assert "never do that" in rendered


def test_a_pinned_subsection_of_a_pinned_section_is_not_pinned_twice() -> None:
    """A section owns its subsections, so pinning both would render it twice."""
    body = _body(
        "# T",
        "i",
        "<!-- always -->",
        "## Rules",
        "outer",
        "<!-- always -->",
        "### Detail",
        "inner",
    )

    pinned = always_sections(body, parse_sections(body))

    assert [s.title for s in pinned] == ["Rules"]
