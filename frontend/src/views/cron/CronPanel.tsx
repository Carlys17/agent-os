import { useId, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ModalShell } from '@/components/ModalShell'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import '@/i18n/en/cron'
import {
  buildSavePayload,
  explainCron,
  humanCountdown,
  humanTime,
  nextRuns,
  parseCron,
  resolveTarget,
  seedForm,
  targetsForChannel,
  type CronForm,
  type DeliveryTarget,
  type DeliveryTargetMap,
  type DeliveryMode,
  type FailureDestMode,
  type PayloadKind,
  type RawJob,
  type SaveBuild,
  type ScheduleKind,
  type SessionTarget,
} from './logic'

// cron.js:105-108 — the four cron presets.
const PRESETS: Array<{ cron: string; label: string }> = [
  { cron: '*/5 * * * *', label: 'Every 5m' },
  { cron: '0 * * * *', label: 'Hourly' },
  { cron: '0 9 * * 1-5', label: 'Weekdays 09:00' },
  { cron: '0 0 * * 0', label: 'Sundays midnight' },
]

// cron.js:88-92 — schedule type options.
const SCHEDULE_TYPES: Array<{ value: ScheduleKind; label: string }> = [
  { value: 'cron', label: 'Cron expression' },
  { value: 'every', label: 'Fixed interval' },
  { value: 'at', label: 'One-time ISO time' },
]

// cron.js:130-134 — job mode options.
const JOB_MODES: Array<{ value: PayloadKind; label: string }> = [
  { value: 'reminder', label: 'Static Reminder (no LLM)' },
  { value: 'script', label: 'Script (no LLM)' },
  { value: 'agent_turn', label: 'Background Agent Task (choose session)' },
  { value: 'system_event', label: 'System Event (Main)' },
]

// cron.js:145-150 — session target options.
const SESSION_TARGETS: Array<{ value: SessionTarget; label: string }> = [
  { value: 'main', label: 'Agent main session' },
  { value: 'current', label: 'Current chat session' },
  { value: 'isolated', label: 'Isolated cron session' },
  { value: 'session', label: 'Named session' },
]

// cron.js:179-184 — delivery mode options.
const DELIVERY_MODES: Array<{ value: DeliveryMode; label: string }> = [
  { value: '', label: 'Default (inferred from session)' },
  { value: 'none', label: 'None (run silently)' },
  { value: 'announce', label: 'Announce to channel' },
  { value: 'webhook', label: 'Post to webhook' },
]

// cron.js:220-224 — failure-destination mode options.
const FD_MODES: Array<{ value: FailureDestMode; label: string }> = [
  { value: '', label: 'Disabled (no separate failure alert)' },
  { value: 'channel', label: 'A channel' },
  { value: 'webhook', label: 'A webhook' },
]

// cron.js:169-173 — wake-mode options.
const WAKE_MODES: Array<{ value: string; label: string }> = [
  { value: 'now', label: 'Now (fire immediately on schedule)' },
  { value: 'next-heartbeat', label: 'Next heartbeat (defer to main loop)' },
]

function CronExplain({ expr }: { expr: string }) {
  // cron.js:1401-1442 — live human summary + up to 3 upcoming runs.
  const trimmed = expr.trim()
  const summary = useMemo(() => {
    if (!trimmed) return null
    const parsed = parseCron(trimmed)
    if (!parsed) return { invalid: true as const }
    return {
      invalid: false as const,
      text: explainCron(trimmed) || 'matches a custom cadence',
      parsed,
    }
  }, [trimmed])

  const upcoming = useMemo(() => {
    if (!summary || summary.invalid) return []
    return nextRuns(summary.parsed, 3)
  }, [summary])

  if (!trimmed) {
    return <div className="cron-explain__human t-data">{t('cron.explainPrompt')}</div>
  }
  if (summary?.invalid) {
    return (
      <div className="cron-explain__human cron-explain--invalid t-data">
        {t('cron.explainInvalid')}
      </div>
    )
  }
  return (
    <div className="cron-explain">
      <div className="cron-explain__human cron-explain--valid t-data">{summary?.text}</div>
      {upcoming.length ? (
        <ul className="cron-explain__upcoming">
          {upcoming.map((d, i) => (
            <li key={i}>
              <span className="cron-mono">{humanCountdown(d)}</span>
              <span className="cron-explain__abs">{humanTime(d)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/** Sentinel option value: "the recipient I want is not in this list". */
const MANUAL_RECIPIENT = '__manual__'

/**
 * The delivery recipient — a picker when the channel's chats are known, a text
 * box otherwise.
 *
 * A free-text box here is what let a *session* key
 * (`agent:main:telegram:direct:1245463966`) be saved as a Telegram chat id; the
 * job then failed at delivery time with nothing but "delivery failed" to show
 * for it. Where the pairing store knows the real chats, offer those instead of
 * asking someone to remember an id.
 */
function RecipientField({
  value,
  targets,
  placeholder,
  onChange,
}: {
  value: string
  targets: DeliveryTarget[]
  placeholder: string
  onChange: (next: string) => void
}) {
  // An id that is not in the list — a group chat outside `group_chat_ids`, or a
  // job saved before this field existed — has to stay editable.
  const [manual, setManual] = useState(() => !!value && !targets.some((t) => t.id === value))
  const asPicker = targets.length > 0 && !manual

  return (
    <label className="cron-field">
      <span className="t-label">{t('cron.fieldRecipient')}</span>
      {asPicker ? (
        <select
          className="cron-input"
          value={value}
          onChange={(e) => {
            if (e.target.value === MANUAL_RECIPIENT) {
              setManual(true)
              onChange('')
              return
            }
            onChange(e.target.value)
          }}
        >
          <option value="">{t('cron.recipientSelect')}</option>
          {targets.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
          <option value={MANUAL_RECIPIENT}>{t('cron.recipientManual')}</option>
        </select>
      ) : (
        <input
          className="cron-input"
          type="text"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  )
}

export function CronPanel({
  job,
  template,
  activeSessionKey,
  saving,
  deliveryTargets,
  onCancel,
  onSubmit,
}: {
  job: RawJob | null
  template: Partial<RawJob> | null
  activeSessionKey: string
  saving: boolean
  /** Known recipients per channel; absent channels keep the free-text input. */
  deliveryTargets?: DeliveryTargetMap
  onCancel: () => void
  onSubmit: (build: Extract<SaveBuild, { ok: true }>) => void
}) {
  const [form, setForm] = useState<CronForm>(() => seedForm(job, template, activeSessionKey))
  const [error, setError] = useState<string | null>(null)
  const titleId = useId()
  const isEdit = !!job

  function set<K extends keyof CronForm>(key: K, value: CronForm[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  // cron.js:997-1057 — the resolved session target (locked flags + message label).
  const targetRes = resolveTarget(form.payloadKind, form.sessionTarget, activeSessionKey)

  // A script job's script IS the job (required); an agent turn may add one as
  // an optional pre-run collector. No other kind runs a file.
  const isScriptJob = form.payloadKind === 'script'
  const canRunScript = isScriptJob || form.payloadKind === 'agent_turn'

  const isAnnounce = form.deliveryMode === 'announce'
  const isWebhook = form.deliveryMode === 'webhook'
  const showBestEffort = isAnnounce || isWebhook
  const isFdChannel = form.fdMode === 'channel'
  const isFdWebhook = form.fdMode === 'webhook'

  function submit(e: React.FormEvent) {
    e.preventDefault()
    // Persist the resolved (possibly coerced) target before building.
    const effectiveForm: CronForm = { ...form, sessionTarget: targetRes.target }
    const build = buildSavePayload(effectiveForm, job, activeSessionKey)
    if (!build.ok) {
      // cron.js:1182,1201,1207,1227,1236 — validation failures surface as a warn
      // toast (legacy UI.toast(..,'warn')); also shown inline for visibility.
      setError(build.error)
      toast.warning(build.error, { id: 'cron-save-validate' })
      return
    }
    setError(null)
    onSubmit(build)
  }

  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onCancel}
      dismissible={!saving}
      overlayClassName="cron-modal__overlay"
      className="cron-panel panel"
    >
      {/* noValidate: validation is JS-only (buildSavePayload), matching the
            legacy view — native constraints (e.g. number min) must not
            intercept submit before our validators run. */}
      <form className="cron-panel__form" noValidate onSubmit={submit}>
        <header className="cron-panel__head">
          <span className="t-label">
            {isEdit ? t('cron.panelEyebrowEdit') : t('cron.panelEyebrowNew')}
          </span>
          <h2 id={titleId} className="cron-panel__title">
            {isEdit ? t('cron.panelTitleEdit') : t('cron.panelTitleNew')}
          </h2>
        </header>

        <div className="cron-panel__body">
          <label className="cron-field">
            <span className="t-label">{t('cron.fieldName')}</span>
            <input
              id="cp-name"
              className="cron-input"
              type="text"
              autoComplete="off"
              placeholder={t('cron.fieldNamePlaceholder')}
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
            />
          </label>

          <label className="cron-field">
            <span className="t-label">{t('cron.fieldScheduleType')}</span>
            <select
              className="cron-input"
              value={form.scheduleKind}
              onChange={(e) => set('scheduleKind', e.target.value as ScheduleKind)}
            >
              {SCHEDULE_TYPES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          {form.scheduleKind === 'cron' ? (
            <div className="cron-field">
              <label className="t-label" htmlFor="cp-cron">
                {t('cron.fieldCronExpression')}
              </label>
              <input
                id="cp-cron"
                className="cron-input cron-input--mono"
                type="text"
                autoComplete="off"
                spellCheck={false}
                placeholder="0 9 * * 1-5"
                value={form.cron}
                onChange={(e) => set('cron', e.target.value)}
              />
              <CronExplain expr={form.cron} />
              <div className="cron-presets">
                <span className="cron-presets__label t-label">{t('cron.fieldPresets')}</span>
                {PRESETS.map((p) => (
                  <button
                    key={p.cron}
                    type="button"
                    className="cron-preset"
                    onClick={() => set('cron', p.cron)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {form.scheduleKind === 'every' ? (
            <label className="cron-field">
              <span className="t-label">{t('cron.fieldInterval')}</span>
              <input
                className="cron-input"
                type="number"
                min="1"
                placeholder="60"
                value={form.every}
                onChange={(e) => set('every', e.target.value)}
              />
            </label>
          ) : null}

          {form.scheduleKind === 'at' ? (
            <label className="cron-field">
              <span className="t-label">{t('cron.fieldIsoTime')}</span>
              <input
                className="cron-input cron-input--mono"
                type="text"
                placeholder="2026-05-18T09:00:00+08:00"
                value={form.at}
                onChange={(e) => set('at', e.target.value)}
              />
            </label>
          ) : null}

          <label className="cron-field">
            <span className="t-label">{t('cron.fieldTimezone')}</span>
            <input
              className="cron-input cron-input--mono"
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder={t('cron.fieldTimezonePlaceholder')}
              value={form.tz}
              onChange={(e) => set('tz', e.target.value)}
            />
            <span className="cron-field__hint">{t('cron.fieldTimezoneHint')}</span>
          </label>

          <label className="cron-field">
            <span className="t-label">{t('cron.fieldJobMode')}</span>
            <select
              className="cron-input"
              value={form.payloadKind}
              onChange={(e) => set('payloadKind', e.target.value as PayloadKind)}
            >
              {JOB_MODES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="cron-field">
            <span className="t-label">{t('cron.fieldAgentId')}</span>
            <input
              className="cron-input"
              type="text"
              placeholder={t('cron.fieldAgentIdPlaceholder')}
              value={form.agentId}
              onChange={(e) => set('agentId', e.target.value)}
            />
          </label>

          <label className="cron-field">
            <span className="t-label">{t('cron.fieldSessionTarget')}</span>
            <select
              className="cron-input"
              value={targetRes.target}
              disabled={targetRes.locked}
              onChange={(e) => set('sessionTarget', e.target.value as SessionTarget)}
            >
              {SESSION_TARGETS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          {targetRes.showTargetSessionRow ? (
            <label className="cron-field">
              <span className="t-label">
                {targetRes.target === 'current' ? t('cron.targetCurrent') : t('cron.targetNamed')}
              </span>
              <input
                className="cron-input"
                type="text"
                placeholder={t('cron.fieldSessionPlaceholder')}
                value={form.targetSessionKey}
                onChange={(e) => set('targetSessionKey', e.target.value)}
              />
            </label>
          ) : null}

          {isScriptJob ? null : (
            <label className="cron-field">
              <span className="t-label">{targetRes.messageLabel}</span>
              <textarea
                className="cron-input cron-input--textarea"
                rows={4}
                placeholder={t('cron.fieldMessagePlaceholder')}
                value={form.message}
                onChange={(e) => set('message', e.target.value)}
              />
            </label>
          )}

          {canRunScript ? (
            <>
              <label className="cron-field">
                <span className="t-label">
                  {isScriptJob ? t('cron.fieldScript') : t('cron.fieldPreRunScript')}
                </span>
                <input
                  className="cron-input"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={isScriptJob ? 'watch-memory.sh' : '(optional) watch-rss.py'}
                  value={form.script}
                  onChange={(e) => set('script', e.target.value)}
                />
                <span className="cron-field__hint">
                  {t('cron.scriptHintLead')}{' '}
                  {isScriptJob ? t('cron.scriptHintDelivered') : t('cron.scriptHintContext')}
                </span>
              </label>

              <label className="cron-field">
                <span className="t-label">{t('cron.fieldScriptArgs')}</span>
                <input
                  className="cron-input"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={t('cron.fieldScriptArgsPlaceholder')}
                  value={form.scriptArgs}
                  onChange={(e) => set('scriptArgs', e.target.value)}
                />
                <span className="cron-field__hint">{t('cron.scriptArgsHint')}</span>
              </label>

              <label className="cron-field">
                <span className="t-label">{t('cron.fieldWorkingDir')}</span>
                <input
                  className="cron-input"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={t('cron.fieldWorkingDirPlaceholder')}
                  value={form.workdir}
                  onChange={(e) => set('workdir', e.target.value)}
                />
              </label>
            </>
          ) : null}

          {isScriptJob || (canRunScript && form.script.trim()) ? (
            <div className="cron-field cron-elevated tone-danger">
              <p className="cron-elevated__warning">{t('cron.scriptWarning')}</p>
            </div>
          ) : null}

          {form.payloadKind === 'agent_turn' ? (
            <div className="cron-field cron-elevated tone-danger">
              <label className="cron-elevated__toggle">
                <input
                  type="checkbox"
                  checked={form.elevated}
                  onChange={(e) => set('elevated', e.target.checked)}
                />
                <span className="t-label">{t('cron.fieldElevated')}</span>
              </label>
              <p className="cron-elevated__warning">{t('cron.elevatedWarning')}</p>
            </div>
          ) : null}

          <details className="cron-advanced">
            <summary className="cron-advanced__summary">{t('cron.advancedDelivery')}</summary>
            <div className="cron-advanced__body">
              <label className="cron-field">
                <span className="t-label">{t('cron.fieldWakeMode')}</span>
                <select
                  className="cron-input"
                  value={form.wakeMode}
                  onChange={(e) => set('wakeMode', e.target.value)}
                >
                  {WAKE_MODES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="cron-field">
                <span className="t-label">{t('cron.fieldDeliveryMode')}</span>
                <select
                  className="cron-input"
                  value={form.deliveryMode}
                  onChange={(e) => set('deliveryMode', e.target.value as DeliveryMode)}
                >
                  {DELIVERY_MODES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>

              {isAnnounce ? (
                <>
                  <label className="cron-field">
                    <span className="t-label">{t('cron.fieldChannel')}</span>
                    <input
                      className="cron-input"
                      type="text"
                      placeholder={t('cron.fieldChannelPlaceholder')}
                      value={form.deliveryChannel}
                      onChange={(e) => set('deliveryChannel', e.target.value)}
                    />
                  </label>
                  <RecipientField
                    value={form.deliveryTo}
                    targets={targetsForChannel(deliveryTargets, form.deliveryChannel)}
                    placeholder={t('cron.fieldChatPlaceholder')}
                    onChange={(next) => set('deliveryTo', next)}
                  />
                  <label className="cron-field">
                    <span className="t-label">{t('cron.fieldAccountId')}</span>
                    <input
                      className="cron-input"
                      type="text"
                      value={form.deliveryAccount}
                      onChange={(e) => set('deliveryAccount', e.target.value)}
                    />
                  </label>
                </>
              ) : null}

              {isWebhook ? (
                <>
                  <label className="cron-field">
                    <span className="t-label">{t('cron.fieldWebhookUrl')}</span>
                    <input
                      className="cron-input cron-input--mono"
                      type="url"
                      placeholder={t('cron.fieldWebhookUrlPlaceholder')}
                      value={form.deliveryWebhookUrl}
                      onChange={(e) => set('deliveryWebhookUrl', e.target.value)}
                    />
                  </label>
                  <label className="cron-field">
                    <span className="t-label">{t('cron.fieldWebhookToken')}</span>
                    <input
                      className="cron-input"
                      type="password"
                      placeholder={t('cron.fieldWebhookTokenPlaceholder')}
                      value={form.deliveryWebhookToken}
                      onChange={(e) => set('deliveryWebhookToken', e.target.value)}
                    />
                  </label>
                </>
              ) : null}

              {showBestEffort ? (
                <label className="cron-toggle">
                  <input
                    type="checkbox"
                    checked={form.deliveryBestEffort}
                    onChange={(e) => set('deliveryBestEffort', e.target.checked)}
                  />
                  <span>{t('cron.fieldBestEffort')}</span>
                </label>
              ) : null}

              <details className="cron-advanced cron-advanced--nested">
                <summary className="cron-advanced__summary">{t('cron.failureDestination')}</summary>
                <div className="cron-advanced__body">
                  <label className="cron-field">
                    <span className="t-label">{t('cron.fieldRouteFailures')}</span>
                    <select
                      className="cron-input"
                      value={form.fdMode}
                      onChange={(e) => set('fdMode', e.target.value as FailureDestMode)}
                    >
                      {FD_MODES.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  {isFdChannel ? (
                    <>
                      <label className="cron-field">
                        <span className="t-label">{t('cron.fieldChannel')}</span>
                        <input
                          className="cron-input"
                          type="text"
                          placeholder={t('cron.fieldChannelPlaceholder')}
                          value={form.fdChannel}
                          onChange={(e) => set('fdChannel', e.target.value)}
                        />
                      </label>
                      <RecipientField
                        value={form.fdTo}
                        targets={targetsForChannel(deliveryTargets, form.fdChannel)}
                        placeholder={t('cron.fieldFailureChatPlaceholder')}
                        onChange={(next) => set('fdTo', next)}
                      />
                      <label className="cron-field">
                        <span className="t-label">{t('cron.fieldAccountId')}</span>
                        <input
                          className="cron-input"
                          type="text"
                          value={form.fdAccount}
                          onChange={(e) => set('fdAccount', e.target.value)}
                        />
                      </label>
                    </>
                  ) : null}

                  {isFdWebhook ? (
                    <>
                      <label className="cron-field">
                        <span className="t-label">{t('cron.fieldWebhookUrl')}</span>
                        <input
                          className="cron-input cron-input--mono"
                          type="url"
                          placeholder={t('cron.fieldFailureWebhookPlaceholder')}
                          value={form.fdWebhookUrl}
                          onChange={(e) => set('fdWebhookUrl', e.target.value)}
                        />
                      </label>
                      <label className="cron-field">
                        <span className="t-label">{t('cron.fieldWebhookToken')}</span>
                        <input
                          className="cron-input"
                          type="password"
                          placeholder={t('cron.fieldWebhookTokenPlaceholder')}
                          value={form.fdWebhookToken}
                          onChange={(e) => set('fdWebhookToken', e.target.value)}
                        />
                      </label>
                    </>
                  ) : null}
                </div>
              </details>
            </div>
          </details>

          <label className="cron-toggle">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set('enabled', e.target.checked)}
            />
            <span>{t('cron.fieldEnabled')}</span>
          </label>

          {error ? (
            <p className="cron-panel__error" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <footer className="cron-panel__foot">
          <Button type="button" variant="ghost" disabled={saving} onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={saving}>
            {t('cron.saveSchedule')}
          </Button>
        </footer>
      </form>
    </ModalShell>
  )
}
