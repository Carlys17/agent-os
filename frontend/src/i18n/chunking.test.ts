import { readFileSync, readdirSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { en } from './en'

/**
 * The rules that keep view copy out of the entry bundle (#261).
 *
 * `t()` is synchronous, so a namespace has to be registered before anything
 * reads it — which the bundler guarantees only if the module that reads it also
 * imports it. These are static checks: they catch a missing import at
 * `npm run check`, where the alternative is a key rendered raw in a view
 * nobody opened during review.
 */

const srcDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function sourceFiles(directory: string): string[] {
  const found: string[] = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) found.push(...sourceFiles(path))
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) found.push(path)
  }
  return found
}

const FILES = sourceFiles(srcDir).map((path) => ({
  path: relative(srcDir, path),
  text: readFileSync(path, 'utf8'),
}))

const NAMESPACES = Object.keys(en)

/** Namespaces the entry bundle carries, read off the imports that make it so. */
const EAGER = new Set(
  [...readFileSync(resolve(srcDir, 'i18n/index.ts'), 'utf8').matchAll(/^import '\.\/en\/(\w+)'$/gm)]
    .map((match) => match[1] as string)
    .filter((name) => NAMESPACES.includes(name)),
)

/** `t('logs.title')` / `tPlural('overview.eventsCount', n)` -> `logs`, `overview`. */
function namespacesUsedIn(text: string): string[] {
  const used = [...text.matchAll(/\bt(?:Plural)?\(\s*'(\w+)\./g)].map((match) => match[1] as string)
  return [...new Set(used)].filter((name) => NAMESPACES.includes(name))
}

describe('catalog chunking', () => {
  it('keeps only shared namespaces eager', () => {
    // A view namespace here would put its copy back in the entry bundle, which
    // is the regression the budget gate would report several PRs later.
    expect([...EAGER].sort()).toEqual(['common', 'shell'])
  })

  it('imports its namespace in every module that translates from it', () => {
    const missing: string[] = []
    for (const { path, text } of FILES) {
      if (path.startsWith('i18n/en/')) continue
      for (const namespace of namespacesUsedIn(text)) {
        if (EAGER.has(namespace)) continue
        if (text.includes(`'@/i18n/en/${namespace}'`)) continue
        missing.push(`${path} translates ${namespace}.* without importing @/i18n/en/${namespace}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('never pulls the full catalog into runtime code', () => {
    // `import type { en }` is fine — types are erased. A value import is not:
    // it drags all seven namespaces into the importing chunk.
    const offenders = FILES.filter(({ path }) => path !== 'i18n/en/index.ts')
      .filter(({ text }) =>
        /^import\s+(?!type\b)[^;\n]*from '(?:@\/i18n\/en|\.{1,2}\/en)'$/m.test(text),
      )
      .map(({ path }) => path)
    expect(offenders).toEqual([])
  })

  it('registers a namespace as a side effect of importing its module', () => {
    // Without this, the side-effect imports above would be dead code a future
    // "unused import" cleanup could delete.
    for (const namespace of NAMESPACES) {
      const text = readFileSync(resolve(srcDir, `i18n/en/${namespace}.ts`), 'utf8')
      expect(text, `${namespace}.ts`).toContain(`defineNamespace('${namespace}'`)
    }
  })
})
