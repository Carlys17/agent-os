import { approvals } from './approvals'
import { common } from './common'
import { env } from './env'
import { health } from './health'
import { logs } from './logs'
import { overview } from './overview'
import { shell } from './shell'

/**
 * The English catalog — the default locale and the fallback for every other
 * locale. Its shape is the source of truth for `MessageKey`, so adding a
 * namespace here is what makes its keys callable from `t()`.
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
