import { create } from 'zustand'
import { hasCatalog, putCatalog } from './registry'
import type { PartialMessages } from './types'

/** A BCP 47 primary subtag that has a catalog registered. */
export type Locale = string

export const DEFAULT_LOCALE = 'en'

/**
 * Register a locale's messages, keyed by lowercased tag. A future locale ships
 * as its own directory plus one `registerCatalog('pt', pt)` call — this module
 * never needs editing again. English is seeded by the registry itself and
 * filled in namespace by namespace as catalog modules load.
 */
export function registerCatalog(tag: string, messages: PartialMessages): void {
  putCatalog(tag.trim().toLowerCase(), messages)
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
  const raw = String(candidate ?? '')
    .trim()
    .toLowerCase()
  if (!raw) return DEFAULT_LOCALE
  if (hasCatalog(raw)) return raw
  const primary = raw.split(/[-_]/)[0] ?? ''
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
