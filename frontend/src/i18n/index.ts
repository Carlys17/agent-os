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
  type Locale,
} from './locale'
export type { MessageKey, PartialMessages } from './types'

const PLACEHOLDER = /\{(\w+)\}/g

type Catalog = Record<string, Record<string, string | undefined> | undefined>

/**
 * Trailing words that mark a numeric placeholder as an identifier or a machine
 * code rather than a quantity. Those render raw in every locale: `port 8,080`,
 * `session 1,024` and `HTTP 1,001` are bugs, not localisation.
 *
 * The rule is deliberately on the *name*, not the value, because the type
 * alone cannot tell a count from a port. Matching is on the last word of the
 * placeholder — split on camelCase and `_` — so `socketPort`, `exit_code` and
 * `sessionId` are already covered and this set only grows for a genuinely new
 * kind of identifier. Everything else numeric is a quantity and gets grouped.
 */
const RAW_TAIL_WORDS = new Set([
  'bytes',
  'code',
  'id',
  'index',
  'line',
  'offset',
  'pid',
  'port',
  'status',
  'version',
  'year',
])

/** `'httpStatus'` -> `'status'`, `'exit_code'` -> `'code'`, `'HTTPStatus'` -> `'status'`. */
function tailWord(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .split(/[\s_]+/)
  return (words[words.length - 1] ?? '').toLowerCase()
}

/**
 * One formatter per locale. `Intl.NumberFormat` construction is the expensive
 * half of the API and `t()` runs on every render of every label.
 */
const NUMBER_FORMATS = new Map<string, Intl.NumberFormat>()

function formatFor(locale: string): Intl.NumberFormat {
  let format = NUMBER_FORMATS.get(locale)
  if (!format) {
    format = new Intl.NumberFormat(locale)
    NUMBER_FORMATS.set(locale, format)
  }
  return format
}

/**
 * Render a quantity for the active locale.
 *
 * Exported for the counters the console renders outside a template: a bare
 * `n.toLocaleString()` there follows the *browser's* locale, which need not be
 * the console's — and a tile whose value and caption disagree on the thousands
 * separator is the visible symptom.
 */
export function formatNumber(value: number): string {
  return Number.isFinite(value) ? formatFor(getLocale()).format(value) : String(value)
}

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(PLACEHOLDER, (match, name: string) => {
    const value = vars[name]
    // An unmatched token stays literal — a template rendering "undefined" to a
    // user is strictly worse than one rendering "{count}".
    if (value === undefined) return match
    // Quantities pick up the active locale's grouping and decimal marks;
    // identifiers stay raw. Non-finite values fall through to `String` so a
    // NaN leaking in from upstream still reads as "NaN", not a localised "∞".
    if (typeof value === 'number' && !RAW_TAIL_WORDS.has(tailWord(name))) {
      return formatNumber(value)
    }
    return String(value)
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
 * Translate a catalog key. A plain function, deliberately not a hook — most of
 * the console's copy lives outside components (view `logic.ts` label maps,
 * module-scope route titles, imperative DOM builders in the chat transcript),
 * and a hook could not serve any of them.
 *
 * English is both the default locale and the per-key fallback, so a single
 * locale build behaves exactly as the hardcoded strings did.
 *
 * Numeric vars are rendered through `Intl.NumberFormat` for the active locale;
 * see `RAW_TAIL_WORDS` for the placeholder names that opt out of that.
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
