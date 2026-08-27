import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/views/projects/projects.css', 'utf8')

describe('Projects view CSS contract', () => {
  it('lays the master list and detail panel out as a responsive split', () => {
    expect(css).toMatch(
      /\.proj-split \{[\s\S]*?grid-template-columns: minmax\(16rem, 22rem\) minmax\(0, 1fr\);/,
    )
    expect(css).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.proj-split \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/,
    )
  })

  it('keeps the knowledge editor vertically resizable with a minimum height', () => {
    expect(css).toMatch(
      /\.proj-knowledge-input \{[\s\S]*?resize: vertical;[\s\S]*?min-height: 6rem;/,
    )
  })

  it('marks the selected project card and constrains card excerpts', () => {
    expect(css).toMatch(/\.proj-card\.is-selected \{[\s\S]*?border-color: var\(--border\);/)
    expect(css).toMatch(/\.proj-card__excerpt \{[\s\S]*?-webkit-line-clamp: 2;/)
  })
})
