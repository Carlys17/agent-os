# Issue #121 implementation evaluation

Reviewed July 30, 2026 against [issue #121](https://github.com/use-agent-os/agent-os/issues/121).
The issue concerns the **WebUI Skills** installed-state chip, not a Gemini Flash
model integration.

## Scope and result

The implementation correctly makes `.sk-chip` self-contained, including its
icon layout, so it works both in the portalled `ModalShell` and inline in the
registry card grid.  It also carries `large` through `InstallButton`'s
`installed` branch and has deterministic regression coverage for both the CSS
contract and dialog component state.

One defect was found during review: `sk-chip--lg` had a minimum height of
`2rem` (32px), while the `Install skill`, `Force install`, and `Installing…`
buttons in the same dialog use Button's default `h-9` size (36px).  This did
not meet the issue's requirement for a consistently sized replacement.  The
implementation was corrected to `2.25rem`, and the CSS regression test now
asserts that exact value.

## Acceptance criteria traceability

| Criterion | Evidence | Status |
| --- | --- | --- |
| One-line installed indicator with a sized check icon in dialog and grid | Unscoped `.sk-chip` defines `inline-flex`, alignment, gap, `white-space: nowrap`; `.sk-chip svg` sets size and `flex-shrink: 0`. | Pass |
| Same rendering inside portal and inline | Required layout is no longer conditional on `.control-surface`, while `ModalShell` portals to `document.body`. | Pass |
| `large` honoured for installed state | `InstallButton` appends `sk-chip--lg`; the variant now matches the default footer button height. | Pass |
| CSS regression coverage | `skills-css.test.ts` asserts the unscoped layout and exact large height; `SkillsPage.test.tsx` asserts the dialog installed chip receives the large class. | Pass |

## Validation performed

`npm exec vitest run src/views/skills/SkillsPage.test.tsx src/views/skills/skills-css.test.ts`

Result: 42 tests passed. The test run emitted only the existing reduced-motion
notice from Motion; it did not affect the result.

## Residual QA note

The issue's broader suggestion to audit all `.control-surface` selectors was
reviewed for dialog-specific selectors. The affected chip layout was the only
load-bearing scoped chip rule. Other dialog selectors are already unscoped, or
the scoped selector targets page-only card behavior. A browser visual smoke
test remains useful before release, but is not required for the deterministic
default test suite.
