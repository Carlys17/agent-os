import { create } from 'zustand'
import { hasCatalog, putCatalog } from './registry'
import type { PartialMessages } from './types'

/** A BCP 47 primary subtag that has a catalog registered. */
export type Locale = string

export const DEFAULT_LOCALE = 'en'

/**
 * Fold a tag onto the key catalogs are stored under, or `null` if it is not a
 * well-formed BCP 47 tag. `Intl.getCanonicalLocales` accepts exactly what
 * `Intl.PluralRules` accepts, so a key that survives this is safe to hand to
 * `tPlural()` later; canonicalising rather than merely lowercasing also folds
 * `pt-br`/`PT-BR` and deprecated aliases (`iw` -> `he`) onto one entry.
 */
function localeKey(tag: string): string | null {
  try {
    return Intl.getCanonicalLocales(tag.trim())[0]?.toLowerCase() ?? null
  } catch {
    return null
  }
}

/**
 * Register a locale's messages. A future locale ships as its own directory plus
 * one `registerCatalog('pt', pt)` call — this module never needs editing again.
 * English is seeded by the registry itself and filled in namespace by namespace
 * as catalog modules load.
 *
 * Catalogs are registered at module load by our own code, so a malformed tag is
 * a programming error and throws here — loudly, at the source. Accepting it
 * would surface instead as a `RangeError` from `new Intl.PluralRules()` at the
 * first pluralised string of some unrelated view.
 */
export function registerCatalog(tag: string, messages: PartialMessages): void {
  const key = localeKey(tag)
  if (key === null) {
    throw new RangeError(`registerCatalog: ${JSON.stringify(tag)} is not a valid BCP 47 locale tag`)
  }
  putCatalog(key, messages)
}

/**
 * Held in a store rather than a bare module variable so a later
 * `useLocale()` subscription can re-render on change without touching a single
 * `t()` call site. Nothing subscribes today — locale is set once at boot.
 */
const useLocaleStore = create<{ locale: Locale }>(() => ({ locale: DEFAULT_LOCALE }))

export function getLocale(): Locale {
  return useLocaleStore.getState().locale
}

/**
 * Narrow a requested tag to one we actually have: exact match first, then the
 * primary subtag (`pt-BR` -> `pt`), then English. Unknown input is never an
 * error — it resolves to the default.
 */
export function resolveLocale(candidate?: string | null): Locale {
  // `_` is tolerated here but not in `registerCatalog`: a candidate arrives from
  // outside (a POSIX-style `pt_BR`, a browser, the gateway) and must resolve
  // rather than throw, while a registered tag is ours to get right.
  const key = localeKey(String(candidate ?? '').replace(/_/g, '-'))
  if (key === null) return DEFAULT_LOCALE
  if (hasCatalog(key)) return key
  const primary = key.split('-')[0] ?? ''
  return hasCatalog(primary) ? primary : DEFAULT_LOCALE
}

export function setLocale(candidate?: string | null): Locale {
  const locale = resolveLocale(candidate)
  useLocaleStore.setState({ locale })
  try {
    document.documentElement.lang = locale
  } catch {
    /* non-DOM environment */
  }
  return locale
}

/**
 * Called once at boot, alongside `initTheme()`. The locale is a constant today;
 * when the gateway starts advertising one, this becomes
 * `setLocale(bootstrap.locale)` in `AppProviders` and nothing else moves.
 */
export function initLocale(): void {
  setLocale(DEFAULT_LOCALE)
}
