import { effectiveElevatedMode } from './logic'
import { t } from '@/i18n'
import '@/i18n/en/chat'

// The elevated-mode pill titles, ported verbatim from _updateElevatedPill
// (chat.js:2314-2343). Resolved per render rather than held as module
// constants: a title frozen at module-evaluation time keeps the boot locale
// forever (#258).

export interface ElevatedPillProps {
  // The browser SESSION override (from the shared elevated-mode store).
  sessionMode: string
  // The GLOBAL permissions.default_mode (from config.get).
  globalMode: string
  // Latched true after a 403 from POST /api/elevated-mode (connection not admitted).
  unavailable: boolean
  onToggle: () => void
}

/**
 * The execution-mode pill in the composer toolbar (chat.js:2314-2343
 * `_updateElevatedPill` + the pill markup at chat.js:1259-1260).
 *
 * The SESSION override wins over the GLOBAL default for the label; the pill is
 * `is-active` whenever an effective elevated mode is in force. Status color
 * flows through the design-system `--tone` gutter (`tone-danger`) — lime stays
 * signal-only — matching the legacy `chat-pill--danger` accent. The shared
 * control radius keeps it aligned with the rest of the composer toolbar.
 */
export function ElevatedPill({
  sessionMode,
  globalMode,
  unavailable,
  onToggle,
}: ElevatedPillProps) {
  if (unavailable) {
    // chat.js:2316-2322 — the latched unavailable state: disabled, distinct label.
    return (
      <button
        type="button"
        className="chat-pill chat-pill--disabled"
        aria-disabled="true"
        title={t('chat.pillTitleUnavailable')}
        onClick={onToggle}
      >
        {t('chat.pillUnavailable')}
      </button>
    )
  }

  const effective = effectiveElevatedMode(sessionMode, globalMode)
  const active = !!effective

  let text: string
  let title: string
  if (sessionMode) {
    // chat.js:2330-2333
    text = t('chat.pillSession', { mode: sessionMode.toUpperCase() })
    title = t('chat.pillTitleSession')
  } else if (globalMode) {
    // chat.js:2334-2337
    text = t('chat.pillGlobal', { mode: globalMode.toUpperCase() })
    title = t('chat.pillTitleGlobal')
  } else {
    // chat.js:2338-2341
    text = t('chat.pillNeutral')
    title = t('chat.pillTitleNeutral')
  }

  return (
    <button
      type="button"
      className={`chat-pill tone-danger${active ? ' is-active' : ''}`}
      title={title}
      onClick={onToggle}
    >
      {text}
    </button>
  )
}
