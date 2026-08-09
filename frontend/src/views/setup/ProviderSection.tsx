// Provider section (setup.js:360-518). Choose a runtime-supported LLM provider,
// fill its core + advanced connection fields, and save via
// onboarding.provider.configure. Secrets are masked (password inputs, never
// echoed). Save/Next are gated on a selected provider.
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import '@/i18n/en/setup'
import { NeedList, PanelHead, SetupField, SetupSelect } from './parts'
import {
  effectiveProvider as effectiveProviderFn,
  isProviderAdvancedField,
  providerAdvancedOpen,
  providerConfigFor,
  providerFieldValue,
  providerRouterSupportText,
  providerRouterSupportTone,
  readScopedFields,
  type Catalog,
  type FieldSpec,
  type OnboardingStatus,
  type ProviderSpec,
  type ScopedField,
  type SetupConfig,
} from './logic'

const TONE_CLASS: Record<string, string> = {
  'is-ready': 'tone-ok',
  'is-direct': 'tone-dim',
  'is-neutral': 'tone-dim',
}

// A field's live edit state (value for text/select, checked for bool).
type Draft = Record<string, { value: string; checked: boolean }>

function seedDraft(fields: FieldSpec[], current: NonNullable<SetupConfig['llm']>): Draft {
  const draft: Draft = {}
  fields.forEach((f) => {
    draft[f.name] = {
      value: f.type === 'bool' ? '' : providerFieldValue(f, current),
      checked: f.type === 'bool' ? Boolean(f.default) : false,
    }
  })
  return draft
}

export function ProviderSection({
  catalog,
  status,
  config,
  onSave,
  onNext,
  onProviderChange,
  saving,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  onSave: (providerId: string, params: Record<string, unknown>) => void
  onNext: () => void
  // Lift the drafted provider up so cross-step consumers (Router preview) see it
  // before Save — legacy _draftProvider read the live <select> (setup.js:430-435).
  onProviderChange?: (providerId: string) => void
  saving: boolean
}) {
  const providers = useMemo(
    () => (catalog.providers || []).filter((p) => p.runtimeSupported),
    [catalog.providers],
  )
  const initial = effectiveProviderFn(status, config)
  const [selected, setSelected] = useState(initial)
  const selectProvider = (providerId: string) => {
    setSelected(providerId)
    onProviderChange?.(providerId)
  }
  const spec: ProviderSpec | undefined = providers.find((p) => p.providerId === selected)
  const values = selected ? providerConfigFor(config, selected) || {} : {}

  const coreFields = (spec?.fields || []).filter((f) => !isProviderAdvancedField(f, spec!))
  const advancedFields = (spec?.fields || []).filter(
    (f) => spec && isProviderAdvancedField(f, spec),
  )

  // Field drafts are keyed by the selected provider so a provider switch reseeds.
  const [draftKey, setDraftKey] = useState(selected)
  const [draft, setDraft] = useState<Draft>(() => seedDraft(spec?.fields || [], values))
  if (draftKey !== selected) {
    setDraftKey(selected)
    setDraft(seedDraft(spec?.fields || [], values))
  }

  const advancedInitiallyOpen = spec ? providerAdvancedOpen(advancedFields, values) : false

  const setValue = (name: string, value: string) =>
    setDraft((d) => ({ ...d, [name]: { ...d[name]!, value } }))
  const setChecked = (name: string, checked: boolean) =>
    setDraft((d) => ({ ...d, [name]: { ...d[name]!, checked } }))

  const supportTone = providerRouterSupportTone(selected ? spec : null)
  const summary = selected
    ? spec?.label || selected
    : `Choose from ${providers.length} supported providers`

  const envMissing = status.llmSource === 'missing_env'
  const envKey = (config.llm || {}).api_key_env || 'the selected API key environment variable'

  const collectAndSave = () => {
    if (!selected) return
    const scoped: ScopedField[] = (spec?.fields || []).map((f) => ({
      name: f.name,
      value: draft[f.name]?.value ?? '',
      checked: draft[f.name]?.checked ?? false,
      type:
        f.type === 'bool' ? 'checkbox' : f.secret || f.type === 'password' ? 'password' : 'text',
      secret: Boolean(f.secret || f.type === 'password'),
      required: Boolean(f.required),
      hidden: false,
    }))
    const params = readScopedFields(scoped, 'provider')
    // A pasted key is the explicit credential source. Do not also submit the
    // catalog's default env reference: provider configuration rejects the two
    // mutually exclusive sources when both are present.
    if (String(params.apiKey || '').trim()) delete params.apiKeyEnv
    onSave(selected, params)
  }

  return (
    <section className="setup-panel panel">
      <PanelHead title={t('setup.providerTitle')} subtitle={summary} />
      <div className="setup-form">
        <label>
          <span>{t('setup.providerTitle')}</span>
          <SetupSelect
            aria-label={t('setup.providerTitle')}
            value={selected}
            onChange={(e) => selectProvider(e.target.value)}
          >
            <option value="" disabled>
              {t('setup.providerChoose')}
            </option>
            {providers.map((p) => (
              <option key={p.providerId} value={p.providerId}>
                {p.label}
              </option>
            ))}
          </SetupSelect>
        </label>

        <div className={`setup-provider-meta ${TONE_CLASS[supportTone]}`}>
          <span className="t-label">{t('setup.providerTiersLabel')}</span>
          <strong className="setup-provider-meta__badge">
            {providerRouterSupportText(selected ? spec : null)}
          </strong>
        </div>

        <NeedList
          items={selected ? spec?.whatYouNeed : [t('setup.providerNeedsPlaceholder')]}
          label={t('setup.providerNeedsLabel')}
        />

        <div className="setup-provider-fields">
          {coreFields.map((f) => (
            <SetupField
              key={f.name}
              field={f}
              value={draft[f.name]?.value ?? ''}
              checked={draft[f.name]?.checked ?? false}
              hidden={false}
              onChange={(v) => setValue(f.name, v)}
              onToggle={(c) => setChecked(f.name, c)}
            />
          ))}
        </div>

        {advancedFields.length > 0 ? (
          <details className="setup-advanced" open={advancedInitiallyOpen}>
            <summary>{t('setup.providerAdvanced')}</summary>
            <div className="setup-advanced__body" aria-label={t('setup.providerConnection')}>
              {advancedFields.map((f) => (
                <SetupField
                  key={f.name}
                  field={f}
                  value={draft[f.name]?.value ?? ''}
                  checked={draft[f.name]?.checked ?? false}
                  hidden={false}
                  onChange={(v) => setValue(f.name, v)}
                  onToggle={(c) => setChecked(f.name, c)}
                />
              ))}
            </div>
          </details>
        ) : null}

        {envMissing ? (
          <div className="setup-warning panel tone-warn tone-rail">
            {t('setup.providerEnvWarning', { key: String(envKey) })}
          </div>
        ) : null}

        <div className="setup-actions">
          <Button type="button" disabled={!selected || saving} onClick={collectAndSave}>
            {t('setup.providerSave')}
          </Button>
          <Button type="button" variant="outline" disabled={!selected} onClick={onNext}>
            {t('setup.next')}
          </Button>
        </div>
      </div>
    </section>
  )
}
