import { create } from 'zustand'
import { en } from './en'
import type { PartialMessages } from './types'

/** A BCP 47 primary subtag that has a catalog registered. */
export type Locale = string

export const DEFAULT_LOCALE = 'en'

/**
 * Registered catalogs, keyed by lowercased tag. A future locale ships as its
 * own directory plus one `registerCatalog('pt', pt)` call — this module never
 * needs editing again.
 */
const CATALOGS = new Map<string, PartialMessages>([[DEFAULT_LOCALE, en]])

export function registerCatalog(tag: string, messages: PartialMessages): void {
  CATALOGS.set(tag.trim().toLowerCase(), messages)
}

export function catalogFor(locale: Locale): PartialMessages {
  return CATALOGS.get(locale) ?? en
}

/**
 * Held in a store rather than a bare module variable so `useLocale()` can
 * re-render subscribers on change without touching a single `t()` call site.
 */
const useLocaleStore = create<{ locale: Locale }>(() => ({ locale: DEFAULT_LOCALE }))

export function getLocale(): Locale {
  return useLocaleStore.getState().locale
}

/**
 * Subscribe to the active locale. `t()` resolves at call time, so a component
 * shows a new locale only once something re-renders it — this hook is that
 * something. `AppShell` subscribes on behalf of the console: its own chrome
 * re-renders, and the routed view is remounted through the view-container key.
 * A component outside that tree needs its own call.
 */
export function useLocale(): Locale {
  return useLocaleStore((s) => s.locale)
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
  if (CATALOGS.has(raw)) return raw
  const primary = raw.split(/[-_]/)[0] ?? ''
  return CATALOGS.has(primary) ? primary : DEFAULT_LOCALE
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
 * `setLocale(bootstrap.locale)` in `AppProviders` and nothing else moves —
 * `setLocale` is already safe to call after boot (#258).
 */
export function initLocale(): void {
  setLocale(DEFAULT_LOCALE)
}
