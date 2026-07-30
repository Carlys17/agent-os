import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/views/skills/skills.css', 'utf8')
const controlCss = readFileSync('src/styles/control-surface.css', 'utf8')

describe('Skills directory CSS contract', () => {
  it('uses a four-source directory navigator with a two-column mobile fallback', () => {
    expect(css).toMatch(
      /\.control-surface \.sk-tabs \{[\s\S]*?grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/,
    )
    expect(css).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.control-surface \.sk-tabs \{[\s\S]*?grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/,
    )
  })

  it('keeps installed status filters compact instead of rendering KPI cards', () => {
    expect(css).toMatch(/\.control-surface \.sk-metrics \{[\s\S]*?display: flex;[\s\S]*?margin: 0;/)
    expect(css).toMatch(
      /\.control-surface \.sk-metric \{[\s\S]*?min-height: 3rem;[\s\S]*?box-shadow: none;/,
    )
    expect(controlCss).not.toMatch(/\.sk-metrics|\.sk-metric(?:__|\s|\.)/)
  })

  it('shows brand artwork at full color and uses readable text statuses', () => {
    expect(css).toMatch(/\.control-surface \.sk-tab__brand \{[\s\S]*?object-fit: cover;/)
    expect(css).toMatch(
      /\.control-surface \.sk-rcard__logo,[\s\S]*?filter: none;[\s\S]*?opacity: 1;/,
    )
    expect(css).toMatch(/\.control-surface \.sk-card__status \{[\s\S]*?font-size:/)
  })

  it('keeps feedback motion subtle and disables transforms for reduced motion', () => {
    expect(css).toMatch(/\.control-surface \.sk-card:hover \{[\s\S]*?translateY\(-1px\)/)
    expect(css).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.control-surface \.sk-card:hover,[\s\S]*?transform: none;/,
    )
  })

  it('prevents skill cards from overflowing grid tracks when skill names are long', () => {
    expect(css).toMatch(/\.sk-grid > \* \{[\s\S]*?min-width:\s*0;/)
    expect(css).toMatch(/\.sk-card \{[\s\S]*?min-width:\s*0;/)
    expect(css).toMatch(/\.sk-card__head \{[\s\S]*?min-width:\s*0;/)
    expect(css).toMatch(
      /\.sk-card__name \{[\s\S]*?overflow:\s*hidden;[\s\S]*?text-overflow:\s*ellipsis;[\s\S]*?white-space:\s*nowrap;/,
    )
  })

  it('makes .sk-chip self-sufficient outside .control-surface with inline-flex, icon sizing, and large variant', () => {
    expect(css).toMatch(
      /\.sk-chip \{[\s\S]*?display: inline-flex;[\s\S]*?align-items: center;[\s\S]*?gap:/,
    )
    expect(css).toMatch(/\.sk-chip svg \{[\s\S]*?width: 0\.75rem;[\s\S]*?height: 0\.75rem;/)
    expect(css).toMatch(
      /\.sk-chip--lg \{[\s\S]*?font-size: 0\.6875rem;[\s\S]*?min-height: 2\.25rem;/,
    )
    expect(css).not.toMatch(/\.control-surface \.sk-chip \{/)
  })

  it('keeps the installed chip the same height as the card install action', () => {
    expect(css).toMatch(
      /\.control-surface \.sk-rcard__foot \[data-slot='button'\] \{[\s\S]*?min-height:\s*2\.25rem;/,
    )
    expect(css).toMatch(
      /\.control-surface \.sk-rcard__foot \.sk-chip--card-action \{[\s\S]*?display:\s*inline-flex;[\s\S]*?min-height:\s*2\.25rem;/,
    )
  })
})
