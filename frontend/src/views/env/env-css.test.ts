import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/views/env/env.css', 'utf8')
const page = readFileSync('src/views/env/EnvPage.tsx', 'utf8')
const controlCss = readFileSync('src/styles/control-surface.css', 'utf8')

describe('Environment screen CSS contract', () => {
  it('keeps the shadowed-variable warning a full-width band, not a subtle hint', () => {
    // It explains the one failure mode operators cannot diagnose on their own.
    expect(css).toMatch(/\.control-surface \.env-warning \{[\s\S]*?display: flex;/)
    expect(css).toMatch(/\.control-surface \.env-warning \{[\s\S]*?border: 1px solid/)
  })

  it('uses a four-way filter row that collapses to two columns on mobile', () => {
    expect(css).toMatch(
      /\.control-surface \.env-filters \{[\s\S]*?grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/,
    )
    expect(css).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.control-surface \.env-filters \{[\s\S]*?grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/,
    )
  })

  it('collapses variable rows to a single column on narrow screens', () => {
    expect(css).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.control-surface \.env-row \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/,
    )
  })

  it('scopes its classes to this view instead of the shared control surface', () => {
    expect(controlCss).not.toMatch(/\.env-row|\.env-filter(?:s|\s|\.)|\.env-badge/)
  })

  it('has no skeleton placeholders', () => {
    // The page keeps its header, counts, and toolbar mounted while loading;
    // swapping the whole view for grey slabs made it flash apart and back
    // together on every visit.
    expect(css).not.toMatch(/skeleton/i)
    expect(page).not.toMatch(/skeleton/i)
  })

  it('stops the refresh spinner for reduced motion', () => {
    expect(css).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.env-spin \{[\s\S]*?animation: none;/,
    )
  })

  it('keeps the modal selectors unscoped because ModalShell portals to body', () => {
    // A `.control-surface` prefix would never match the portalled node, so the
    // panel would render unstyled — which a jsdom test cannot see.
    expect(css).toMatch(/^\.env-modal \{/m)
    expect(css).toMatch(/^\.env-modal__overlay \{/m)
    expect(css).not.toMatch(/\.control-surface \.env-modal/)
  })
})

describe('Environment confirmation dialog wiring', () => {
  it('wraps ModalShell in AnimatePresence', () => {
    // ModalShell enters via motion variants. Without a presence context the
    // overlay stays at its initial opacity of 0: mounted, focus-trapping, and
    // invisible. jsdom reports reduced-motion and takes ModalShell's
    // no-variant branch, so only a source-level check catches this.
    const modalAt = page.indexOf('<ModalShell')
    const presenceAt = page.lastIndexOf('<AnimatePresence>', modalAt)
    expect(modalAt).toBeGreaterThan(-1)
    expect(presenceAt).toBeGreaterThan(-1)
    expect(page.slice(presenceAt, modalAt)).not.toContain('</AnimatePresence>')
  })

  it('uses the in-app dialog rather than a native confirm', () => {
    // Matches a call, not the word: the comment above the state hook explains
    // why window.confirm is avoided and must not trip its own guard.
    expect(page).not.toMatch(/(?<![.\w])(?:window\.)?confirm\(/)
  })
})

describe('Environment header parity with sibling views', () => {
  // control-surface.css grants the shared stage-header treatment through
  // explicit :is() allowlists. A view that forgets to join them silently gets
  // an ad-hoc header — different height, padding, and alignment from every
  // other page — which is exactly how this one drifted the first time.
  const lists = controlCss.match(/:is\(([^)]*stage__header[^)]*)\)/g) ?? []

  it('joins every shared stage-header allowlist that MCP is on', () => {
    const mcpLists = lists.filter((list) => list.includes('.mcp-stage__header'))
    expect(mcpLists.length).toBeGreaterThan(0)
    for (const list of mcpLists) {
      expect(list).toContain('.env-stage__header')
    }
  })

  it('joins the title-block and actions allowlists too', () => {
    expect(controlCss).toMatch(/\.env-stage__title-block/)
    expect(controlCss).toMatch(/\.env-stage__actions/)
  })

  it('does not re-declare the shared header geometry locally', () => {
    // A local copy of the header box would fight the shared rules.
    expect(css).not.toMatch(/\.env-stage__header\s*\{/)
  })

  it('declares its own actions row, as every sibling view does', () => {
    // control-surface only tunes this responsively; the base flex row is
    // per-view. Dropping it leaves the header buttons flush against each other.
    expect(css).toMatch(/\.env-stage__actions \{[\s\S]*?display: flex;[\s\S]*?gap:/)
  })

  it('uses the same subtitle measure as the Skills stage', () => {
    expect(css).toMatch(/\.env-stage__subtitle \{[\s\S]*?max-width: 52ch;/)
  })
})
