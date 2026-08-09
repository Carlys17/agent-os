import { describe, expect, it } from 'vitest'
import { en } from './en'

/**
 * Generic invariants over the catalogs. These are what keep the per-view
 * migration honest — every new namespace is covered the moment it is added to
 * `en`, with no per-view test file to remember to write.
 */

type Leaf = [namespace: string, key: string, value: string]

const LEAVES: Leaf[] = Object.entries(en).flatMap(([namespace, messages]) =>
  Object.entries(messages as Record<string, string>).map(
    ([key, value]) => [namespace, key, value] as Leaf,
  ),
)

function placeholders(value: string): string[] {
  return [...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1] as string).sort()
}

describe('the English catalog', () => {
  it('is not empty', () => {
    expect(LEAVES.length).toBeGreaterThan(0)
  })

  it('has a string value for every key', () => {
    for (const [namespace, key, value] of LEAVES) {
      expect(typeof value, `${namespace}.${key}`).toBe('string')
    }
  })

  it('has no empty or whitespace-padded values', () => {
    // A padded value is the signature of a JSX text node copied across with its
    // surrounding indentation, which silently changes the rendered output.
    for (const [namespace, key, value] of LEAVES) {
      const label = `${namespace}.${key}`
      // `unset` is a legitimate empty label (env's SOURCE_LABELS sentinel).
      if (value === '') continue
      expect(value.trim(), label).toBe(value)
    }
  })

  it('uses exactly two levels — no dots inside a key', () => {
    // `MessageKey` splits on the first dot; a dotted key would produce an
    // unreachable entry.
    for (const [namespace, key] of LEAVES) {
      expect(key, `${namespace}.${key}`).not.toContain('.')
      expect(namespace).not.toContain('.')
    }
  })

  it('pairs every _other plural key with an _one and carries {count} in both', () => {
    const byNamespace = new Map<string, Set<string>>()
    for (const [namespace, key] of LEAVES) {
      const keys = byNamespace.get(namespace) ?? new Set<string>()
      keys.add(key)
      byNamespace.set(namespace, keys)
    }
    let checked = 0
    for (const [namespace, key, value] of LEAVES) {
      if (!key.endsWith('_other')) continue
      checked += 1
      const base = key.slice(0, -'_other'.length)
      const siblings = byNamespace.get(namespace)!
      expect(siblings.has(`${base}_one`), `${namespace}.${base}_one is missing`).toBe(true)
      expect(placeholders(value), `${namespace}.${key}`).toContain('count')
      const one = (en as Record<string, Record<string, string>>)[namespace]![`${base}_one`]!
      expect(placeholders(one), `${namespace}.${base}_one`).toContain('count')
    }
    // Guard the guard: if the plural convention is ever dropped this test would
    // otherwise pass vacuously.
    expect(checked).toBeGreaterThan(0)
  })
})

// Deliberately NOT asserted: that no two keys share a value. Identical copy in
// different contexts (approvals' `scopeSession` and `cardSession` are both
// "Session") is normal — a translator may well render them differently, so
// collapsing them into one key would be the bug.
