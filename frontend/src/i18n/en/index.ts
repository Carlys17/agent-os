import { approvals } from './approvals'
import { common } from './common'
import { env } from './env'
import { health } from './health'
import { logs } from './logs'
import { overview } from './overview'
import { shell } from './shell'

/**
 * Every English namespace in one object.
 *
 * This is the *type* source of truth — `MessageKey` is derived from it, so
 * adding a namespace here is what makes its keys callable from `t()` — and the
 * shape tests read it at runtime.
 *
 * It is NOT how the app loads copy. Importing this module pulls all seven
 * namespaces into whichever chunk does so, which for anything reachable from
 * the entry graph is exactly the growth #261 fixed. Runtime code must import
 * the one namespace it needs (`@/i18n/en/logs`) and let `t()` read the
 * registry; `i18n/chunking.test.ts` enforces that. `src/test/setup.ts` imports
 * this module once so unit tests see the complete catalog, standing in for the
 * views that register their own namespace in the browser.
 */
export const en = {
  approvals,
  common,
  env,
  health,
  logs,
  overview,
  shell,
} as const
