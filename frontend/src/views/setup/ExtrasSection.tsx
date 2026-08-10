// Capabilities section (setup.js:716-957). Five capability cards — web search,
// memory embedding, memory settings, image generation, voice audio — each with
// its own draft state, conditional field enablement (from logic.ts), masked
// secrets, and a Save wired to the matching onboarding.*.configure RPC (memory
// settings uses config.patch). All decision-shaped derivation lives in logic.ts.
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import '@/i18n/en/setup'
import {
  CapabilityBadge,
  EnvRecoveryCommand,
  NeedList,
  PanelHead,
  SetupCheckbox,
  SetupSelect,
} from './parts'
import {
  audioStatusText,
  buildAudioConfigureParams,
  buildImageConfigureParams,
  buildMemoryConfigureParams,
  buildMemorySettingsPatches,
  buildSearchConfigureParams,
  buildXSearchConfigureParams,
  capabilityIsPrimary,
  credentialNeedList,
  envRecoveryCommand,
  imageGenerationStatusText,
  memoryControlFlags,
  memoryEmbeddingStatusText,
  memoryNeedList,
  memorySettingsOverBudget,
  searchStatusText,
  xSearchCredentialText,
  type AuthStatus,
  type CapabilityField,
  type Catalog,
  type OnboardingStatus,
  type ProviderSpec,
  type SetupConfig,
} from './logic'

type ExtrasResetTarget =
  'search' | 'xSearch' | 'memoryEmbedding' | 'memorySettings' | 'image' | 'audio'

function saveVariant(status: OnboardingStatus, name: string): 'default' | 'outline' {
  return capabilityIsPrimary(status, name) ? 'default' : 'outline'
}

// ── Web search (setup.js:716-851) ───────────────────────────────────────────
function SearchCard({
  catalog,
  status,
  config,
  onSave,
  saving,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  onSave: (params: Record<string, unknown>) => void
  saving: boolean
}) {
  const providers = (catalog.searchProviders || []).filter((p) => p.runtimeSupported)
  const initial =
    config.search_provider ||
    providers.find((p) => p.providerId === 'duckduckgo')?.providerId ||
    providers[0]?.providerId ||
    'duckduckgo'
  const [provider, setProvider] = useState(initial)
  const spec: ProviderSpec = providers.find((p) => p.providerId === provider) ||
    providers[0] || {
      providerId: provider,
    }
  const requiresKey = spec.requiresApiKey === true

  const [maxResults, setMaxResults] = useState(String(config.search_max_results || 5))
  const [apiKey, setApiKey] = useState('')
  const [apiKeyEnv, setApiKeyEnv] = useState(
    config.search_api_key_env || (requiresKey ? spec.envKey || '' : '') || '',
  )
  // Re-seed the env-var name to the new provider's envKey on a provider switch,
  // unless the user has typed their own — legacy _syncSearchProviderKeyControls
  // did `envInput.value = spec.envKey || ''` on every change (setup.js:1551-1555;
  // '' when the provider needs no key). Without a touch flag, switching to Brave
  // without typing would save api_key_env:'' instead of 'BRAVE_API_KEY'.
  const [envTouched, setEnvTouched] = useState(false)
  const [envProviderKey, setEnvProviderKey] = useState(provider)
  if (envProviderKey !== provider) {
    setEnvProviderKey(provider)
    if (!envTouched) setApiKeyEnv(requiresKey ? spec.envKey || '' : '')
  }
  const [proxy, setProxy] = useState(config.search_proxy || '')
  const [useEnvProxy, setUseEnvProxy] = useState(config.search_use_env_proxy === true)
  const [fallback, setFallback] = useState(config.search_fallback_policy || 'off')
  const [diagnostics, setDiagnostics] = useState(config.search_diagnostics === true)

  const collect = () => {
    const fields: CapabilityField[] = [
      {
        name: 'max_results',
        value: maxResults,
        checked: false,
        type: 'number',
        secret: false,
        disabled: false,
      },
      {
        name: 'api_key',
        value: apiKey,
        checked: false,
        type: 'password',
        secret: true,
        disabled: !requiresKey,
      },
      {
        name: 'api_key_env',
        value: apiKeyEnv,
        checked: false,
        type: 'text',
        secret: false,
        disabled: !requiresKey,
      },
      { name: 'proxy', value: proxy, checked: false, type: 'text', secret: false, disabled: false },
      {
        name: 'use_env_proxy',
        value: '',
        checked: useEnvProxy,
        type: 'checkbox',
        secret: false,
        disabled: false,
      },
      {
        name: 'fallback_policy',
        value: fallback,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'diagnostics',
        value: '',
        checked: diagnostics,
        type: 'checkbox',
        secret: false,
        disabled: false,
      },
    ].filter((f) => !f.disabled)
    onSave(buildSearchConfigureParams(provider, fields))
  }

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.searchTitle')}</h3>
        <CapabilityBadge status={status} name="search" />
      </div>
      <p className="setup-muted">{searchStatusText(status, config)}</p>
      <EnvRecoveryCommand command={envRecoveryCommand(status, 'search')} />
      <NeedList
        items={credentialNeedList(spec.whatYouNeed, apiKeyEnv || spec.envKey)}
        label={t('setup.searchNeeds')}
      />
      <label>
        <span>{t('setup.fieldProvider')}</span>
        <SetupSelect
          aria-label={t('setup.searchProviderAria')}
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p.providerId} value={p.providerId}>
              {p.label}
            </option>
          ))}
        </SetupSelect>
      </label>
      <label>
        <span>{t('setup.searchMaxResults')}</span>
        <input
          type="number"
          min={1}
          step={1}
          aria-label={t('setup.searchMaxResultsAria')}
          value={maxResults}
          onChange={(e) => setMaxResults(e.target.value)}
        />
      </label>
      {requiresKey ? (
        <div className="setup-advanced__body">
          <label>
            <span>{t('setup.fieldApiKey')}</span>
            <input
              type="password"
              aria-label={t('setup.searchApiKeyAria')}
              placeholder={t('setup.keepCurrentPlaceholder')}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldApiKeyEnv')}</span>
            <input
              aria-label={t('setup.searchApiKeyEnvAria')}
              value={apiKeyEnv}
              placeholder={spec.envKey || 'SEARCH_API_KEY'}
              onChange={(e) => {
                setEnvTouched(true)
                setApiKeyEnv(e.target.value)
              }}
            />
          </label>
        </div>
      ) : null}
      <details
        className="setup-advanced"
        open={Boolean(proxy || useEnvProxy || fallback !== 'off' || diagnostics)}
      >
        <summary>{t('setup.searchAdvanced')}</summary>
        <div className="setup-advanced__body" aria-label={t('setup.searchBehavior')}>
          <label>
            <span>{t('setup.searchProxy')}</span>
            <input
              aria-label={t('setup.searchProxyAria')}
              placeholder={t('setup.searchProxyPlaceholder')}
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
            />
          </label>
          <SetupCheckbox
            ariaLabel={t('setup.searchUseEnvProxy')}
            checked={useEnvProxy}
            onChange={setUseEnvProxy}
          >
            {t('setup.searchUseEnvProxy')}
          </SetupCheckbox>
          <label>
            <span>{t('setup.searchFallback')}</span>
            <SetupSelect
              aria-label={t('setup.searchFallbackAria')}
              value={fallback}
              onChange={(e) => setFallback(e.target.value)}
            >
              <option value="off">{t('setup.searchFallbackOff')}</option>
              <option value="network">{t('setup.searchFallbackNetwork')}</option>
            </SetupSelect>
          </label>
          <SetupCheckbox
            ariaLabel={t('setup.searchDiagnosticsAria')}
            checked={diagnostics}
            onChange={setDiagnostics}
          >
            {t('setup.searchDiagnostics')}
          </SetupCheckbox>
        </div>
      </details>
      <Button
        type="button"
        variant={saveVariant(status, 'search')}
        disabled={saving}
        onClick={collect}
      >
        {t('setup.searchSave')}
      </Button>
    </div>
  )
}

// xAI API values, not display copy: these are sent verbatim and must never be
// translated. Kept as identifiers so the i18n lint does not read them as text.
const X_SEARCH_DEFAULT_MODEL = 'grok-4.5'
const X_SEARCH_EFFORTS = ['low', 'medium', 'high', 'xhigh'] as const

// ── X (Twitter) search ──────────────────────────────────────────────────────
// Not a web-search provider: it answers from X's post index through xAI, so it
// gets its own card rather than a row in the search provider select.
function XSearchCard({
  catalog,
  config,
  authStatus,
  onSave,
  saving,
}: {
  catalog: Catalog
  config: SetupConfig
  authStatus: AuthStatus
  onSave: (params: Record<string, unknown>) => void
  saving: boolean
}) {
  const spec: ProviderSpec = catalog.xSearch?.[0] || { providerId: 'x_search' }
  const current = config.x_search || {}
  const envKey = spec.envKey || 'XAI_API_KEY'

  const [enabled, setEnabled] = useState(current.enabled !== false)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyEnv, setApiKeyEnv] = useState(current.api_key_env || envKey)
  const [model, setModel] = useState(current.model || X_SEARCH_DEFAULT_MODEL)
  const [effort, setEffort] = useState(current.reasoning_effort || '')
  const [timeout, setTimeout] = useState(String(current.timeout_seconds ?? 180))
  const [totalTimeout, setTotalTimeout] = useState(String(current.total_timeout_seconds ?? 300))
  const [retries, setRetries] = useState(String(current.retries ?? 2))

  const collect = () => {
    const field = (name: string, value: string, type: string, secret = false): CapabilityField => ({
      name,
      value,
      checked: false,
      type,
      secret,
      disabled: false,
    })
    const fields: CapabilityField[] = [
      field('api_key', apiKey, 'password', true),
      field('api_key_env', apiKeyEnv, 'text'),
      field('model', model, 'text'),
      field('reasoning_effort', effort, 'text'),
      field('timeout_seconds', timeout, 'number'),
      field('total_timeout_seconds', totalTimeout, 'number'),
      field('retries', retries, 'number'),
    ]
    onSave(buildXSearchConfigureParams(enabled, fields))
  }

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.xSearchTitle')}</h3>
      </div>
      <p className="setup-muted">{t('setup.xSearchHint')}</p>
      <p className="setup-muted">{xSearchCredentialText(authStatus, config)}</p>
      <NeedList
        items={credentialNeedList(spec.whatYouNeed, apiKeyEnv || envKey)}
        label={t('setup.xSearchNeeds')}
      />
      <SetupCheckbox
        ariaLabel={t('setup.xSearchEnabledAria')}
        checked={enabled}
        onChange={setEnabled}
      >
        {t('setup.xSearchEnabled')}
      </SetupCheckbox>
      <label>
        <span>{t('setup.fieldApiKey')}</span>
        <input
          type="password"
          aria-label={t('setup.xSearchApiKeyAria')}
          placeholder={t('setup.keepCurrentPlaceholder')}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </label>
      <label>
        <span>{t('setup.fieldApiKeyEnv')}</span>
        <input
          aria-label={t('setup.xSearchApiKeyEnvAria')}
          value={apiKeyEnv}
          placeholder={envKey}
          onChange={(e) => setApiKeyEnv(e.target.value)}
        />
      </label>
      <label>
        <span>{t('setup.xSearchModel')}</span>
        <input
          aria-label={t('setup.xSearchModelAria')}
          value={model}
          placeholder={X_SEARCH_DEFAULT_MODEL}
          onChange={(e) => setModel(e.target.value)}
        />
      </label>
      <details
        className="setup-advanced"
        open={Boolean(effort || timeout !== '180' || totalTimeout !== '300' || retries !== '2')}
      >
        <summary>{t('setup.xSearchAdvanced')}</summary>
        <div className="setup-advanced__body" aria-label={t('setup.xSearchBehavior')}>
          <label>
            <span>{t('setup.xSearchEffort')}</span>
            <SetupSelect
              aria-label={t('setup.xSearchEffortAria')}
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
            >
              <option value="">{t('setup.xSearchEffortDefault')}</option>
              {X_SEARCH_EFFORTS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </SetupSelect>
          </label>
          <label>
            <span>{t('setup.xSearchTimeout')}</span>
            <input
              type="number"
              min={30}
              max={300}
              step={1}
              aria-label={t('setup.xSearchTimeoutAria')}
              value={timeout}
              onChange={(e) => setTimeout(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.xSearchTotalTimeout')}</span>
            <input
              type="number"
              min={30}
              max={600}
              step={1}
              aria-label={t('setup.xSearchTotalTimeoutAria')}
              value={totalTimeout}
              onChange={(e) => setTotalTimeout(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.xSearchRetries')}</span>
            <input
              type="number"
              min={0}
              max={5}
              step={1}
              aria-label={t('setup.xSearchRetriesAria')}
              value={retries}
              onChange={(e) => setRetries(e.target.value)}
            />
          </label>
        </div>
      </details>
      <Button type="button" variant="outline" disabled={saving} onClick={collect}>
        {t('setup.xSearchSave')}
      </Button>
    </div>
  )
}

// ── Memory embedding (setup.js:732-876) ─────────────────────────────────────
function MemoryEmbeddingCard({
  catalog,
  status,
  config,
  onSave,
  saving,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  onSave: (params: Record<string, unknown>) => void
  saving: boolean
}) {
  const providers = catalog.memoryEmbeddingProviders || []
  const current = (config.memory || {}).embedding || {}
  const initial = current.provider || current.mode || 'auto'
  const [provider, setProvider] = useState(initial)
  const spec: ProviderSpec = providers.find((p) => p.providerId === provider) ||
    providers[0] || {
      providerId: provider,
    }
  const flags = memoryControlFlags(provider, spec)

  const remote = (current.remote || {}) as Record<string, string>
  const local = (current.local || {}) as Record<string, string>
  const ollama = (current.ollama || {}) as Record<string, string>

  const [model, setModel] = useState(remote.model || ollama.model || '')
  const [apiKey, setApiKey] = useState('')
  const [apiKeyEnv, setApiKeyEnv] = useState(
    remote.api_key_env || (flags.apiKeyEnabled ? spec.envKey || '' : '') || '',
  )
  const [baseUrl, setBaseUrl] = useState(remote.base_url || ollama.base_url || '')
  const [onnxDir, setOnnxDir] = useState(local.onnx_dir || '')

  const collect = () => {
    const fields: CapabilityField[] = [
      {
        name: 'model',
        value: model,
        checked: false,
        type: 'text',
        secret: false,
        disabled: !flags.remoteControlEnabled,
      },
      {
        name: 'api_key',
        value: apiKey,
        checked: false,
        type: 'password',
        secret: true,
        disabled: !flags.apiKeyEnabled,
      },
      {
        name: 'api_key_env',
        value: apiKeyEnv,
        checked: false,
        type: 'text',
        secret: false,
        disabled: !flags.apiKeyEnabled,
      },
      {
        name: 'base_url',
        value: baseUrl,
        checked: false,
        type: 'text',
        secret: false,
        disabled: !flags.remoteControlEnabled,
      },
      {
        name: 'onnx_dir',
        value: onnxDir,
        checked: false,
        type: 'text',
        secret: false,
        disabled: !flags.localControlEnabled,
      },
    ]
    onSave(buildMemoryConfigureParams(provider, fields))
  }

  const apiKeyLabel = provider === 'auto' ? 'Fallback API key' : 'API key'
  const remoteSummary =
    provider === 'auto'
      ? t('setup.memoryRemoteFallbackSummary')
      : t('setup.memoryConnectionSummary')

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.memoryEmbeddingTitle')}</h3>
        <CapabilityBadge status={status} name="memory_embedding" />
      </div>
      <p className="setup-muted">{memoryEmbeddingStatusText(status, config, provider)}</p>
      <EnvRecoveryCommand command={envRecoveryCommand(status, 'memory_embedding')} />
      <NeedList
        items={memoryNeedList(spec, provider, apiKeyEnv || spec.envKey)}
        label={t('setup.memoryNeeds')}
      />
      <label>
        <span>{t('setup.fieldProvider')}</span>
        <SetupSelect
          aria-label={t('setup.memoryEmbeddingProviderAria')}
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p.providerId} value={p.providerId}>
              {p.label}
            </option>
          ))}
        </SetupSelect>
      </label>
      {flags.localControlEnabled ? (
        <label>
          <span>{t('setup.memoryOnnxDir')}</span>
          <input
            aria-label={t('setup.memoryOnnxDirAria')}
            placeholder={t('setup.memoryOnnxDirPlaceholder')}
            value={onnxDir}
            onChange={(e) => setOnnxDir(e.target.value)}
          />
        </label>
      ) : null}
      {flags.hasRemoteOptions ? (
        <details className="setup-advanced" open={provider !== 'auto'}>
          <summary>{remoteSummary}</summary>
          <div className="setup-advanced__body" aria-label={t('setup.memoryEmbeddingConnection')}>
            {flags.remoteControlEnabled ? (
              <label>
                <span>{t('setup.fieldModel')}</span>
                <input
                  aria-label={t('setup.memoryEmbeddingModelAria')}
                  value={model}
                  placeholder={
                    provider === 'ollama' ? 'nomic-embed-text' : 'text-embedding-3-small'
                  }
                  onChange={(e) => setModel(e.target.value)}
                />
              </label>
            ) : null}
            {flags.apiKeyEnabled ? (
              <>
                <label>
                  <span>{apiKeyLabel}</span>
                  <input
                    type="password"
                    aria-label={t('setup.memoryEmbeddingApiKeyAria')}
                    placeholder={t('setup.keepCurrentPlaceholder')}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </label>
                <label>
                  <span>{t('setup.fieldApiKeyEnv')}</span>
                  <input
                    aria-label={t('setup.memoryEmbeddingApiKeyEnvAria')}
                    value={apiKeyEnv}
                    placeholder={spec.envKey || 'OPENAI_API_KEY'}
                    onChange={(e) => setApiKeyEnv(e.target.value)}
                  />
                </label>
              </>
            ) : null}
            {flags.remoteControlEnabled ? (
              <label>
                <span>{t('setup.fieldBaseUrl')}</span>
                <input
                  aria-label={t('setup.memoryEmbeddingBaseUrlAria')}
                  value={baseUrl}
                  placeholder={
                    provider === 'ollama' ? 'http://localhost:11434' : 'https://api.openai.com/v1'
                  }
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </label>
            ) : null}
          </div>
        </details>
      ) : null}
      <Button
        type="button"
        variant={saveVariant(status, 'memory_embedding')}
        disabled={saving}
        onClick={collect}
      >
        {t('setup.memoryEmbeddingSave')}
      </Button>
    </div>
  )
}

// ── Memory settings (setup.js:877-904) ──────────────────────────────────────
function MemorySettingsCard({
  config,
  onSave,
  saving,
}: {
  config: SetupConfig
  onSave: (patches: Record<string, unknown>) => void
  saving: boolean
}) {
  const memory = config.memory || {}
  const [providerName, setProviderName] = useState(String(memory.provider?.name || ''))
  const [memoryLimit, setMemoryLimit] = useState(String(memory.curated_memory_char_limit ?? 4000))
  const [userLimit, setUserLimit] = useState(String(memory.curated_user_char_limit ?? 2000))
  const [injectLimit, setInjectLimit] = useState(String(memory.inject_limit ?? 6400))

  const overBudget = memorySettingsOverBudget(
    Number.parseInt(memoryLimit || '0', 10),
    Number.parseInt(userLimit || '0', 10),
    Number.parseInt(injectLimit || '0', 10),
  )

  const collect = () =>
    onSave(buildMemorySettingsPatches({ providerName, memoryLimit, userLimit, injectLimit }))

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.memoryTitle')}</h3>
      </div>
      <p className="setup-muted">{t('setup.memoryBlurb')}</p>
      <label>
        <span>{t('setup.memoryProvider')}</span>
        <SetupSelect
          aria-label={t('setup.memoryProviderAria')}
          value={providerName}
          onChange={(e) => setProviderName(e.target.value)}
        >
          <option value="">{t('setup.memoryProviderNone')}</option>
          <option value="mem0">{t('setup.memoryProviderMem0')}</option>
        </SetupSelect>
      </label>
      <label>
        <span>{t('setup.memoryBudget')}</span>
        <input
          type="number"
          min={0}
          step={1}
          aria-label={t('setup.memoryBudgetAria')}
          value={memoryLimit}
          onChange={(e) => setMemoryLimit(e.target.value)}
        />
      </label>
      <label>
        <span>{t('setup.memoryUserBudget')}</span>
        <input
          type="number"
          min={0}
          step={1}
          aria-label={t('setup.memoryUserBudgetAria')}
          value={userLimit}
          onChange={(e) => setUserLimit(e.target.value)}
        />
      </label>
      <label>
        <span>{t('setup.memoryInjectLimit')}</span>
        <input
          type="number"
          min={0}
          step={1}
          aria-label={t('setup.memoryInjectLimitAria')}
          value={injectLimit}
          onChange={(e) => setInjectLimit(e.target.value)}
        />
      </label>
      {overBudget ? (
        <div className="setup-warning panel tone-warn tone-rail">{t('setup.memoryOverBudget')}</div>
      ) : null}
      <Button type="button" variant="outline" disabled={saving} onClick={collect}>
        {t('setup.memorySave')}
      </Button>
    </div>
  )
}

// ── Image generation (setup.js:905-926) ─────────────────────────────────────
function ImageCard({
  catalog,
  status,
  config,
  onSave,
  saving,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  onSave: (params: Record<string, unknown>) => void
  saving: boolean
}) {
  const providers = (catalog.imageGenerationProviders || []).filter((p) => p.runtimeSupported)
  const initial =
    status.imageGenerationProvider ||
    (status.imageGenerationPrimary || '').split('/')[0] ||
    providers[0]?.providerId ||
    'openrouter'
  const [provider, setProvider] = useState(initial)
  const spec: ProviderSpec = providers.find((p) => p.providerId === provider) ||
    providers[0] || {
      providerId: provider,
    }
  const imageConfig = config.image_generation || {}
  const providerConfig = (imageConfig.providers || {})[provider] || {}
  const enabledInitial = status.imageGenerationEnabled === false ? false : true

  const [enabled, setEnabled] = useState(enabledInitial)
  const [primary, setPrimary] = useState(
    String(status.imageGenerationPrimary || spec.defaultModel || ''),
  )
  const [apiKey, setApiKey] = useState('')
  const [apiKeyEnv, setApiKeyEnv] = useState(
    String(providerConfig.api_key_env || (spec.requiresApiKey ? spec.envKey : '') || ''),
  )
  const [baseUrl, setBaseUrl] = useState(
    String(providerConfig.base_url || spec.defaultBaseUrl || ''),
  )
  const statusText =
    enabled === enabledInitial
      ? imageGenerationStatusText(status)
      : enabled
        ? 'Save to make image generation available to agents.'
        : 'Save to hide image generation from agents.'

  const needs = enabled
    ? credentialNeedList(spec.whatYouNeed, apiKeyEnv || spec.envKey)
    : ['No key required while image generation is disabled.']

  const collect = () => {
    const fields: CapabilityField[] = [
      {
        name: 'primary',
        value: primary,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'api_key',
        value: apiKey,
        checked: false,
        type: 'password',
        secret: true,
        disabled: false,
      },
      {
        name: 'api_key_env',
        value: apiKeyEnv,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'base_url',
        value: baseUrl,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
    ]
    onSave(buildImageConfigureParams(provider, enabled, fields))
  }

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.imageTitle')}</h3>
        <CapabilityBadge status={status} name="image_generation" />
      </div>
      <p className="setup-muted">{statusText}</p>
      <EnvRecoveryCommand command={envRecoveryCommand(status, 'image_generation')} />
      <NeedList items={needs} label={t('setup.imageNeeds')} />
      <SetupCheckbox
        ariaLabel={t('setup.imageEnabledAria')}
        checked={enabled}
        className="setup-capability-toggle"
        onChange={setEnabled}
      >
        {t('setup.imageEnable')}
      </SetupCheckbox>
      {enabled ? (
        <div className="setup-advanced__body">
          <label>
            <span>{t('setup.fieldProvider')}</span>
            <SetupSelect
              aria-label={t('setup.imageProviderAria')}
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.providerId} value={p.providerId}>
                  {p.label}
                </option>
              ))}
            </SetupSelect>
          </label>
          <label>
            <span>{t('setup.imagePrimaryModel')}</span>
            <input
              aria-label={t('setup.imagePrimaryModelAria')}
              value={primary}
              onChange={(e) => setPrimary(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldApiKey')}</span>
            <input
              type="password"
              aria-label={t('setup.imageApiKeyAria')}
              placeholder={t('setup.keepCurrentPlaceholder')}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldApiKeyEnv')}</span>
            <input
              aria-label={t('setup.imageApiKeyEnvAria')}
              value={apiKeyEnv}
              placeholder={spec.envKey || 'OPENROUTER_API_KEY'}
              onChange={(e) => setApiKeyEnv(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldBaseUrl')}</span>
            <input
              aria-label={t('setup.imageBaseUrlAria')}
              value={baseUrl}
              placeholder={spec.defaultBaseUrl || 'https://api.openai.com/v1'}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </label>
        </div>
      ) : null}
      <Button
        type="button"
        variant={saveVariant(status, 'image_generation')}
        disabled={saving}
        onClick={collect}
      >
        {t('setup.imageSave')}
      </Button>
    </div>
  )
}

// ── Voice audio (setup.js:927-950) ──────────────────────────────────────────
function AudioCard({
  catalog,
  status,
  config,
  onSave,
  saving,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  onSave: (params: Record<string, unknown>) => void
  saving: boolean
}) {
  const providers = (catalog.audioProviders || []).filter((p) => p.runtimeSupported)
  const initial = status.audioProvider || providers[0]?.providerId || 'elevenlabs'
  const [provider, setProvider] = useState(initial)
  const spec: ProviderSpec = providers.find((p) => p.providerId === provider) ||
    providers[0] || {
      providerId: provider,
    }
  const audioConfig = config.audio || {}
  const providerConfig = (audioConfig.providers || {})[provider] || {}
  const tts = (audioConfig.tts || {}) as Record<string, string>
  const enabledInitial = status.audioEnabled === true || audioConfig.enabled === true

  const [enabled, setEnabled] = useState(enabledInitial)
  const [apiKey, setApiKey] = useState('')
  const [apiKeyEnv, setApiKeyEnv] = useState(
    String(providerConfig.api_key_env || (spec.requiresApiKey ? spec.envKey : '') || ''),
  )
  const [baseUrl, setBaseUrl] = useState(
    String(providerConfig.base_url || spec.defaultBaseUrl || ''),
  )
  const [ttsVoice, setTtsVoice] = useState(String(tts.voice || spec.defaultTtsVoice || ''))
  const [ttsModel, setTtsModel] = useState(String(tts.model || spec.defaultTtsModel || ''))
  const [languageCode, setLanguageCode] = useState(
    String(tts.language_code || spec.defaultLanguageCode || ''),
  )
  const statusText =
    enabled === enabledInitial
      ? audioStatusText(status)
      : enabled
        ? 'Save to make voice audio available to agents.'
        : 'Save to hide voice audio from agents.'

  const needs = enabled
    ? credentialNeedList(spec.whatYouNeed, apiKeyEnv || spec.envKey)
    : ['No key required while voice audio is disabled.']

  const collect = () => {
    const fields: CapabilityField[] = [
      {
        name: 'api_key',
        value: apiKey,
        checked: false,
        type: 'password',
        secret: true,
        disabled: false,
      },
      {
        name: 'api_key_env',
        value: apiKeyEnv,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'base_url',
        value: baseUrl,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'tts_voice',
        value: ttsVoice,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'tts_model',
        value: ttsModel,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
      {
        name: 'language_code',
        value: languageCode,
        checked: false,
        type: 'text',
        secret: false,
        disabled: false,
      },
    ]
    onSave(buildAudioConfigureParams(provider, enabled, fields))
  }

  return (
    <div className="setup-mini panel">
      <div className="setup-mini__head">
        <h3 className="t-label">{t('setup.audioTitle')}</h3>
        <CapabilityBadge status={status} name="audio" />
      </div>
      <p className="setup-muted">{statusText}</p>
      <EnvRecoveryCommand command={envRecoveryCommand(status, 'audio')} />
      <NeedList items={needs} label={t('setup.audioNeeds')} />
      <SetupCheckbox
        ariaLabel={t('setup.audioEnabledAria')}
        checked={enabled}
        className="setup-capability-toggle"
        onChange={setEnabled}
      >
        {t('setup.audioEnable')}
      </SetupCheckbox>
      {enabled ? (
        <div className="setup-advanced__body">
          <label>
            <span>{t('setup.fieldProvider')}</span>
            <SetupSelect
              aria-label={t('setup.audioProviderAria')}
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.providerId} value={p.providerId}>
                  {p.label}
                </option>
              ))}
            </SetupSelect>
          </label>
          <label>
            <span>{t('setup.fieldApiKey')}</span>
            <input
              type="password"
              aria-label={t('setup.audioApiKeyAria')}
              placeholder={t('setup.keepCurrentPlaceholder')}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldApiKeyEnv')}</span>
            <input
              aria-label={t('setup.audioApiKeyEnvAria')}
              value={apiKeyEnv}
              placeholder={spec.envKey || 'ELEVENLABS_API_KEY'}
              onChange={(e) => setApiKeyEnv(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.fieldBaseUrl')}</span>
            <input
              aria-label={t('setup.audioBaseUrlAria')}
              value={baseUrl}
              placeholder={spec.defaultBaseUrl || 'https://api.elevenlabs.io'}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.audioTtsVoice')}</span>
            <input
              aria-label={t('setup.audioTtsVoiceAria')}
              value={ttsVoice}
              placeholder={spec.defaultTtsVoice || 'voice id'}
              onChange={(e) => setTtsVoice(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.audioTtsModel')}</span>
            <input
              aria-label={t('setup.audioTtsModelAria')}
              value={ttsModel}
              placeholder={spec.defaultTtsModel || 'eleven_multilingual_v2'}
              onChange={(e) => setTtsModel(e.target.value)}
            />
          </label>
          <label>
            <span>{t('setup.audioLanguage')}</span>
            <input
              aria-label={t('setup.audioLanguageAria')}
              value={languageCode}
              placeholder="zh-CN, en-US, en-GB"
              onChange={(e) => setLanguageCode(e.target.value)}
            />
          </label>
        </div>
      ) : null}
      <Button
        type="button"
        variant={saveVariant(status, 'audio')}
        disabled={saving}
        onClick={collect}
      >
        {t('setup.audioSave')}
      </Button>
    </div>
  )
}

export function ExtrasSection({
  catalog,
  status,
  config,
  authStatus,
  onSaveSearch,
  onSaveXSearch,
  onSaveMemory,
  onSaveMemorySettings,
  onSaveImage,
  onSaveAudio,
  onBack,
  onNext,
  saving,
  resetVersions,
  conflicts,
  onDirtyChange,
}: {
  catalog: Catalog
  status: OnboardingStatus
  config: SetupConfig
  authStatus: AuthStatus
  onSaveSearch: (params: Record<string, unknown>) => void
  onSaveXSearch: (params: Record<string, unknown>) => void
  onSaveMemory: (params: Record<string, unknown>) => void
  onSaveMemorySettings: (patches: Record<string, unknown>) => void
  onSaveImage: (params: Record<string, unknown>) => void
  onSaveAudio: (params: Record<string, unknown>) => void
  onBack: () => void
  onNext: () => void
  saving: boolean
  resetVersions: {
    search: number
    xSearch: number
    memoryEmbedding: number
    memorySettings: number
    image: number
    audio: number
  }
  conflicts: Record<ExtrasResetTarget, boolean>
  onDirtyChange: (target: ExtrasResetTarget) => void
}) {
  return (
    <section className="setup-panel panel">
      <PanelHead title={t('setup.extrasTitle')} subtitle={t('setup.extrasSubtitle')} />
      <div className="setup-extras">
        <div className="setup-capability-slot" onChangeCapture={() => onDirtyChange('search')}>
          <SearchCard
            key={`search:${resetVersions.search}`}
            catalog={catalog}
            status={status}
            config={config}
            onSave={onSaveSearch}
            saving={saving || conflicts.search}
          />
        </div>
        <div className="setup-capability-slot" onChangeCapture={() => onDirtyChange('xSearch')}>
          <XSearchCard
            key={`x-search:${resetVersions.xSearch}`}
            catalog={catalog}
            config={config}
            authStatus={authStatus}
            onSave={onSaveXSearch}
            saving={saving || conflicts.xSearch}
          />
        </div>
        <div
          className="setup-capability-slot"
          onChangeCapture={() => onDirtyChange('memoryEmbedding')}
        >
          <MemoryEmbeddingCard
            key={`memory-embedding:${resetVersions.memoryEmbedding}`}
            catalog={catalog}
            status={status}
            config={config}
            onSave={onSaveMemory}
            saving={saving || conflicts.memoryEmbedding}
          />
        </div>
        <div
          className="setup-capability-slot"
          onChangeCapture={() => onDirtyChange('memorySettings')}
        >
          <MemorySettingsCard
            key={`memory-settings:${resetVersions.memorySettings}`}
            config={config}
            onSave={onSaveMemorySettings}
            saving={saving || conflicts.memorySettings}
          />
        </div>
        <div className="setup-capability-slot" onChangeCapture={() => onDirtyChange('image')}>
          <ImageCard
            key={`image:${resetVersions.image}`}
            catalog={catalog}
            status={status}
            config={config}
            onSave={onSaveImage}
            saving={saving || conflicts.image}
          />
        </div>
        <div className="setup-capability-slot" onChangeCapture={() => onDirtyChange('audio')}>
          <AudioCard
            key={`audio:${resetVersions.audio}`}
            catalog={catalog}
            status={status}
            config={config}
            onSave={onSaveAudio}
            saving={saving || conflicts.audio}
          />
        </div>
      </div>
      <div className="setup-actions">
        <Button type="button" variant="outline" onClick={onBack}>
          {t('setup.back')}
        </Button>
        <Button type="button" variant="outline" onClick={onNext}>
          {t('setup.next')}
        </Button>
      </div>
    </section>
  )
}
