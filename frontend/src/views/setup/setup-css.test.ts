import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/views/setup/setup.css', 'utf8')

describe('Setup embedded surface CSS contract', () => {
  it('keeps the inner panel out of the rounded clipping context', () => {
    expect(css).toMatch(
      /\.setup-stage--embedded \.setup-panel,[\s\S]*?\.control-surface \.setup-stage--embedded \.setup-panel \{[\s\S]*?overflow: visible;/,
    )
  })

  it('gives router selects and capability checkboxes dedicated control styling', () => {
    expect(css).toMatch(
      /\.setup-select select \{[\s\S]*?appearance: none;[\s\S]*?padding: 0\.58rem 2\.35rem 0\.58rem 0\.75rem;/,
    )
    expect(css).toMatch(
      /\.setup-router-toolbar input\[type='number'\] \{[\s\S]*?box-sizing: border-box;[\s\S]*?padding: 0\.58rem 2\.65rem 0\.58rem 0\.75rem;/,
    )
    expect(css).toMatch(
      /\.setup-check__input:checked \+ \.setup-check__control \{[\s\S]*?background: var\(--primary\);/,
    )
    expect(css).toMatch(/\.setup-check > \.setup-check__control \{[\s\S]*?color: transparent;/)
    expect(css).toMatch(
      /\.setup-capability-toggle \{[\s\S]*?width: 100%;[\s\S]*?border-radius: var\(--radius-control\);/,
    )
    expect(css).toContain(".setup-tier-table input:not([type='checkbox'])")
  })

  it('uses a soft disclosure surface instead of another hard nested border', () => {
    expect(css).toMatch(/\.setup-advanced \{[\s\S]*?border: 0;[\s\S]*?background: color-mix\(/)
  })

  it('styles the read-only tier provider chip like the tier chip beside it', () => {
    // #142 replaced a free-text provider input with a <code> chip; without a
    // rule it renders at the browser default next to a tokenised sibling.
    expect(css).toMatch(
      /\.setup-provider-chip \{[\s\S]*?font-family: var\(--font-mono\);[\s\S]*?text-overflow: ellipsis;/,
    )
    expect(css).toMatch(/\.setup-hint--field \{[\s\S]*?display: block;/)
  })

  it('gives the model column room for a real model id', () => {
    // 'anthropic/claude-opus-4.8' rendered as 'anthropic/claude-opus' at the
    // previous width, and the model cell is the one that must stay readable.
    expect(css).toMatch(
      /grid-template-columns:\s*\n?\s*4\.5rem minmax\(5\.5rem, 0\.6fr\) minmax\(14rem, 2fr\)/,
    )
  })

  it('reflows router tier rows into labelled mobile fields', () => {
    expect(css).toMatch(
      /@media \(max-width: 720px\) \{[\s\S]*?\.setup-tier-table__row \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\) 6\.5rem;/,
    )
  })
})
