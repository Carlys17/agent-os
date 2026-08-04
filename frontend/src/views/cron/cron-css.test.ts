import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/views/cron/cron.css', 'utf8')

describe('Cron scheduling workspace CSS contract', () => {
  it('integrates summary metrics into one automation-clock surface', () => {
    expect(css).toMatch(
      /\.control-surface \.cron-command \.cron-stats \{[\s\S]*?grid-template-columns: 1\.35fr repeat\(3, minmax\(0, 1fr\)\);/,
    )
    expect(css).toMatch(/\.cron-command \{[\s\S]*?border-radius: var\(--radius-surface\);/)
    expect(css).toMatch(
      /\.control-surface \.cron-command \.cron-stat:first-child \{[^}]*box-shadow: none;/,
    )
    expect(css).not.toMatch(/\.cron-command \.cron-stat:first-child \{[^}]*inset 2px 0 0/)
  })

  it('uses rounded status-aware job inventory cards', () => {
    expect(css).toMatch(
      /\.control-surface \.cron-card\.cron-card \{[\s\S]*?border-radius: var\(--radius-surface\);/,
    )
    expect(css).toMatch(
      /\.control-surface \.cron-card\.cron-card::before \{[\s\S]*?background: var\(--tone, var\(--dim\)\);/,
    )
  })

  it('keeps unbreakable session keys inside the card grid track', () => {
    // Every box between the grid track and the text must be able to shrink,
    // otherwise a colon-separated session key sets the card's min-content width.
    expect(css).toMatch(/\.cron-cards > \*,[\s\S]*?\.cron-cards__item \{[\s\S]*?min-width: 0;/)
    expect(css).toMatch(/\.cron-card__meta > div \{[\s\S]*?min-width: 0;/)
    expect(css).toMatch(/\.cron-card__meta dd \{[\s\S]*?min-width: 0;/)
    expect(css).toMatch(/\.cron-card__meta dd \{[\s\S]*?text-overflow: ellipsis;/)
    expect(css).toMatch(/\.cron-card__message dd \{[\s\S]*?overflow-wrap: anywhere;/)
  })

  it('lays the cron id row out as value plus copy affordance', () => {
    expect(css).toMatch(/\.cron-card__id dd \{[\s\S]*?justify-content: flex-end;/)
    expect(css).toMatch(/\.cron-card__id-value \{[\s\S]*?text-overflow: ellipsis;/)
  })

  it('contains small-screen controls and disables decorative motion', () => {
    expect(css).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.cron-search-wrap,[\s\S]*?\.control-surface \.cron-search \{[\s\S]*?width: 100%;/,
    )
    expect(css).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.cron-command,[\s\S]*?\.cron-stat__value,[\s\S]*?animation: none;/,
    )
  })
})
