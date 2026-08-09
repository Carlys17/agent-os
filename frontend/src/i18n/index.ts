import { en } from './en'
import { catalogFor, getLocale } from './locale'
import type { Args, MessageKey, PluralBase, Vars } from './types'

export {
  DEFAULT_LOCALE,
  getLocale,
  initLocale,
  registerCatalog,
  resolveLocale,
  setLocale,
  useLocale,
  type Locale,
} from './locale'
export type { MessageKey, PartialMessages } from './types'

const PLACEHOLDER = /\{(\w+)\}/g

type Catalog = Record<string, Record<string, string | undefined> | undefined>

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(PLACEHOLDER, (match, name: string) => {
    const value = vars[name]
    // An unmatched token stays literal — a template rendering "undefined" to a
    // user is strictly worse than one rendering "{count}".
    return value === undefined ? match : String(value)
  })
}

/** Raw lookup, active locale first, then English, with no interpolation. */
function lookupOptional(key: string): string | undefined {
  const dot = key.indexOf('.')
  if (dot < 0) return undefined
  const ns = key.slice(0, dot)
  const leaf = key.slice(dot + 1)
  const fromLocale = (catalogFor(getLocale()) as Catalog)[ns]?.[leaf]
  if (typeof fromLocale === 'string') return fromLocale
  const fromEn = (en as Catalog)[ns]?.[leaf]
  return typeof fromEn === 'string' ? fromEn : undefined
}

function lookup(key: string): string {
  const found = lookupOptional(key)
  if (found !== undefined) return found
  if (import.meta.env.DEV) console.warn(`[i18n] missing key: ${key}`)
  // Render the key rather than an empty node: a missing string should be
  // obvious in the UI, not invisible.
  return key
}

/**
 * Translate a catalog key. A plain function, deliberately not a hook — much of
 * the console's copy lives outside components (view `logic.ts` label maps,
 * imperative DOM builders in the chat transcript), and a hook could not serve
 * any of them.
 *
 * It resolves against the locale that is active *at call time*, so it must be
 * called from inside a function that re-runs after a locale change, never at
 * module scope where the result would freeze for the life of the page (#258 —
 * `no-restricted-syntax` in eslint.config.js enforces this). `useLocale()` is
 * what makes a component re-run.
 *
 * English is both the default locale and the per-key fallback, so a single
 * locale build behaves exactly as the hardcoded strings did.
 */
export function t<K extends MessageKey>(key: K, ...args: Args<K>): string {
  return interpolate(lookup(key), args[0] as Vars | undefined)
}

/**
 * Translate a count-dependent key pair, `<base>_one` / `<base>_other`, using
 * `Intl.PluralRules` — a platform API, so pluralisation costs no dependency.
 * `count` is injected into the template automatically.
 *
 * Locales with categories beyond one/other degrade to `_other` rather than
 * failing, so a translator can add `_few` later without a code change.
 */
export function tPlural<B extends PluralBase>(base: B, count: number, vars?: Vars): string {
  const category = new Intl.PluralRules(getLocale()).select(count)
  const template = lookupOptional(`${base}_${category}`) ?? lookup(`${base}_other`)
  return interpolate(template, { count, ...vars })
}
