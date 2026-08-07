import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const sheetCss = readFileSync('src/components/KeyboardShortcuts.css', 'utf8')
const promptCss = readFileSync('src/components/ApprovalPrompt.css', 'utf8')

describe('shortcut overlay CSS contract', () => {
  it('stays on the route-dialog layer, below the blocking approval prompt', () => {
    // The approval prompt is the one surface that must never be covered; it
    // owns --z-critical-approval alone (see approval-prompt-css.test.ts). A
    // cheat-sheet that borrowed that token would paint over a pending approval,
    // because it portals into <body> later.
    expect(promptCss).toMatch(/\.approval-backdrop \{[\s\S]*?z-index: var\(--z-critical-approval\)/)
    expect(sheetCss).not.toMatch(/z-index:\s*var\(--z-critical-approval\)/)
    expect(sheetCss).toMatch(/\.shortcut-overlay \{[\s\S]*?z-index: 60;/)
  })

  it('sizes the sheet so a long list scrolls inside it', () => {
    expect(sheetCss).toMatch(/\.shortcut-sheet \{[\s\S]*?max-height: calc\(100dvh - 48px\);/)
    expect(sheetCss).toMatch(/\.shortcut-sheet__body \{[\s\S]*?overflow-y: auto;/)
  })

  it('draws keycaps from theme tokens rather than hardcoded colours', () => {
    expect(sheetCss).toMatch(
      /\.shortcut-sheet__kbd \{[\s\S]*?background: var\(--elevated\);[\s\S]*?color: var\(--foreground\);/,
    )
  })
})
