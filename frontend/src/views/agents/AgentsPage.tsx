import './agents.css'
import { useEffect, useId, useState } from 'react'
import { useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence } from 'motion/react'
import { MessageSquareIcon, PencilIcon, PlusIcon, RefreshCwIcon, Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'
import { MotionListItem } from '@/lib/motion'
import { ModalShell } from '@/components/ModalShell'
import { Button } from '@/components/ui/button'
import { useRpc } from '@/app/providers'
import { t } from '@/i18n'
import '@/i18n/en/agents'
import {
  agentDisplay,
  agentStats,
  agentToForm,
  buildCreatePayload,
  buildUpdatePayload,
  isFormDirty,
  isNoOpUpdate,
  parseToolsInput,
  validateCreate,
  type AgentForm,
  type RawAgent,
} from './logic'

// agents.js:84-91 — the single read; refreshed imperatively (no legacy poll).
interface AgentsList {
  agents?: RawAgent[]
}

interface AgentsListError {
  code?: string
  message?: string
}

function toneClass(tone: 'ok' | 'info'): string {
  return tone === 'ok' ? 'tone-ok' : 'tone-info'
}

// ── Create / Edit dialog ─────────────────────────────────────────────────────
function AgentDialog({
  mode,
  seed,
  saving,
  onCancel,
  onCreate,
  onSave,
}: {
  mode: 'create' | 'edit'
  seed: AgentForm
  saving: boolean
  onCancel: () => void
  onCreate: (id: string, name: string) => void
  onSave: (initial: AgentForm, current: AgentForm) => void
}) {
  const [form, setForm] = useState<AgentForm>(seed)
  const [toolsText, setToolsText] = useState(seed.tools.join(', '))
  const [idError, setIdError] = useState<string | null>(null)
  const [showDiscard, setShowDiscard] = useState(false)
  const titleId = useId()
  const isCreate = mode === 'create'
  const idDisabled = !isCreate // id is never editable post-create (agents.js:324)

  // agents.js:272-275,307-312 — the edit form is dirty vs its seed (tools live
  // in the free-text field, so fold it into the comparison snapshot).
  const dirty = !isCreate && isFormDirty(seed, { ...form, tools: parseToolsInput(toolsText) })

  function set<K extends keyof AgentForm>(key: K, value: AgentForm[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  // agents.js:307-312,499-506 — a dirty edit prompts to discard on close;
  // create mode / a non-dirty edit closes immediately.
  function attemptClose() {
    if (saving) return
    if (dirty) {
      setShowDiscard(true)
      return
    }
    onCancel()
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (isCreate) {
      const errors = validateCreate({ id: form.id, name: form.name })
      if (errors.id) {
        setIdError(errors.id)
        return
      }
      onCreate(form.id, form.name)
      return
    }
    onSave(seed, { ...form, tools: parseToolsInput(toolsText) })
  }

  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={attemptClose}
      overlayClassName="ag-modal__overlay"
      className="ag-modal panel"
    >
      <form className="ag-dialog" onSubmit={submit}>
        <header className="ag-dialog__head">
          <span className="t-label">{t('agents.eyebrow')}</span>
          <h2 id={titleId} className="ag-dialog__title">
            {isCreate
              ? t('agents.dialogCreateTitle')
              : t('agents.dialogEditTitle', { id: seed.id })}
          </h2>
        </header>

        <div className="ag-dialog__body">
          <label className="ag-field">
            <span className="t-label">{t('agents.fieldId')}</span>
            <input
              className="ag-input"
              autoComplete="off"
              disabled={idDisabled}
              value={form.id}
              placeholder={t('agents.fieldIdPlaceholder')}
              aria-invalid={idError ? true : undefined}
              onChange={(e) => {
                set('id', e.target.value)
                if (idError) setIdError(null)
              }}
            />
            {idError ? (
              <span className="ag-field__error" role="alert">
                {idError}
              </span>
            ) : null}
          </label>

          <label className="ag-field">
            <span className="t-label">{t('agents.fieldName')}</span>
            <input
              className="ag-input"
              autoComplete="off"
              value={form.name}
              placeholder={t('agents.fieldNamePlaceholder')}
              onChange={(e) => set('name', e.target.value)}
            />
          </label>

          {isCreate ? (
            <p className="ag-dialog__hint">{t('agents.createHint')}</p>
          ) : (
            <>
              <label className="ag-field">
                <span className="t-label">{t('agents.fieldDescription')}</span>
                <input
                  className="ag-input"
                  autoComplete="off"
                  value={form.description}
                  placeholder={t('agents.fieldDescriptionPlaceholder')}
                  onChange={(e) => set('description', e.target.value)}
                />
              </label>

              <details
                className="ag-dialog__advanced"
                open={Boolean(
                  form.workspace || form.agentDir || form.tools.length || !form.enabled,
                )}
              >
                <summary>{t('agents.advancedSummary')}</summary>
                <label className="ag-field">
                  <span className="t-label">{t('agents.fieldTools')}</span>
                  <input
                    className="ag-input"
                    autoComplete="off"
                    value={toolsText}
                    placeholder={t('agents.fieldToolsPlaceholder')}
                    onChange={(e) => setToolsText(e.target.value)}
                  />
                </label>
                <label className="ag-field">
                  <span className="t-label">{t('agents.fieldWorkspace')}</span>
                  <input
                    className="ag-input"
                    autoComplete="off"
                    value={form.workspace}
                    placeholder={t('agents.fieldWorkspacePlaceholder')}
                    onChange={(e) => set('workspace', e.target.value)}
                  />
                </label>
                <label className="ag-field">
                  <span className="t-label">{t('agents.fieldAgentDir')}</span>
                  <input
                    className="ag-input"
                    autoComplete="off"
                    value={form.agentDir}
                    placeholder={t('agents.fieldAgentDirPlaceholder')}
                    onChange={(e) => set('agentDir', e.target.value)}
                  />
                </label>
                <label className="ag-field ag-field--inline">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(e) => set('enabled', e.target.checked)}
                  />
                  <span>{t('agents.fieldEnabled')}</span>
                </label>
              </details>
            </>
          )}
        </div>

        <footer className="ag-dialog__foot">
          <Button type="button" variant="ghost" disabled={saving} onClick={attemptClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={saving}>
            {isCreate ? t('agents.submitCreate') : t('agents.submitSave')}
          </Button>
        </footer>
      </form>

      {showDiscard ? (
        <ConfirmDialog
          title={t('agents.discardTitle')}
          body={t('agents.discardBody')}
          confirmLabel={t('agents.discardConfirm')}
          cancelLabel={t('agents.discardCancel')}
          onCancel={() => setShowDiscard(false)}
          onConfirm={() => {
            setShowDiscard(false)
            onCancel()
          }}
        />
      ) : null}
    </ModalShell>
  )
}

// ── Reusable destructive confirmation (alertdialog) ──────────────────────────
function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = t('common.cancel'),
  busy = false,
  onCancel,
  onConfirm,
}: {
  title: string
  body: React.ReactNode
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const titleId = useId()
  const bodyId = useId()
  return (
    <ModalShell
      role="alertdialog"
      labelledBy={titleId}
      describedBy={bodyId}
      onClose={busy ? () => {} : onCancel}
      overlayClassName="ag-modal__overlay"
      className="ag-modal panel ag-confirm-modal"
    >
      <div className="ag-dialog ag-confirm">
        <header className="ag-dialog__head">
          <h2 id={titleId} className="ag-dialog__title">
            {title}
          </h2>
        </header>
        <p id={bodyId} className="ag-confirm__body">
          {body}
        </p>
        <footer className="ag-dialog__foot">
          <Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button type="button" variant="destructive" disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </footer>
      </div>
    </ModalShell>
  )
}

// ── Agent card ───────────────────────────────────────────────────────────────
function AgentCard({
  agent,
  busy,
  onChat,
  onEdit,
  onCustomize,
  onDelete,
}: {
  agent: RawAgent
  busy: boolean
  onChat: (id: string) => void
  onEdit: (agent: RawAgent) => void
  onCustomize: (id: string) => void
  onDelete: (id: string) => void
}) {
  const d = agentDisplay(agent)
  return (
    <article
      className={`panel ag-card ${toneClass(d.tone)}`}
      aria-label={t('agents.cardLandmark', { id: d.id })}
    >
      <header className="ag-card__head">
        <span
          className={`ag-card__dot tone-${d.tone === 'ok' ? 'ok' : 'info'}`}
          aria-hidden="true"
        />
        <span className="ag-card__id" title={d.id}>
          {d.id}
        </span>
        <span className={`ag-card__type t-data ${toneClass(d.tone)}`}>{d.type}</span>
      </header>

      <div className="ag-card__name">{d.name}</div>
      {d.description ? <p className="ag-card__desc">{d.description}</p> : null}

      <dl className="ag-card__meta">
        {d.model ? (
          <div>
            <dt className="t-label">{t('agents.cardModel')}</dt>
            <dd className="t-data ag-mono">{d.model}</dd>
          </div>
        ) : null}
        {d.toolCount ? (
          <div>
            <dt className="t-label">{t('agents.cardTools')}</dt>
            <dd className="t-data">{d.toolCount}</dd>
          </div>
        ) : null}
        {d.skillCount ? (
          <div>
            <dt className="t-label">{t('agents.cardSkills')}</dt>
            <dd className="t-data">{d.skillCount}</dd>
          </div>
        ) : null}
      </dl>

      {d.toolChips.length ? (
        <div className="ag-card__chips">
          <span className="ag-card__chips-label t-label">{t('agents.cardTools')}</span>
          {d.toolChips.map((t) => (
            <span key={t} className="ag-chip t-data">
              {t}
            </span>
          ))}
          {d.overflow ? <span className="ag-chip ag-chip--dim t-data">+{d.overflow}</span> : null}
        </div>
      ) : null}

      <footer className="ag-card__actions">
        <Button type="button" size="sm" variant="outline" onClick={() => onChat(d.id)}>
          <MessageSquareIcon />
          <span>{t('agents.cardChat')}</span>
        </Button>
        {d.isBuiltin ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            title={t('agents.cardCustomizeTitle')}
            onClick={() => onCustomize(d.id)}
          >
            <PlusIcon />
            <span>{t('agents.cardCustomize')}</span>
          </Button>
        ) : (
          <>
            <Button type="button" size="sm" variant="outline" onClick={() => onEdit(agent)}>
              <PencilIcon />
              <span>{t('agents.cardEdit')}</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => onDelete(d.id)}
            >
              <Trash2Icon />
              <span>{t('agents.cardDelete')}</span>
            </Button>
          </>
        )}
      </footer>
    </article>
  )
}

function StatTile({
  label,
  value,
  hint,
  hero,
}: {
  label: string
  value: React.ReactNode
  hint: React.ReactNode
  hero?: boolean
}) {
  return (
    <div className={`ag-stat${hero ? ' ag-stat--hero' : ''}`} aria-label={label}>
      <span className="ag-stat__label t-label">{label}</span>
      <strong className="ag-stat__value t-data">{value}</strong>
      <span className="ag-stat__hint">{hint}</span>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
type DialogState =
  | { kind: 'none' }
  | { kind: 'create'; seed: AgentForm }
  | { kind: 'edit'; seed: AgentForm }
  | { kind: 'delete'; id: string }

const EMPTY_FORM: AgentForm = {
  id: '',
  name: '',
  description: '',
  tools: [],
  workspace: '',
  agentDir: '',
  enabled: true,
}

export function AgentsPage() {
  const rpc = useRpc()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<DialogState>({ kind: 'none' })

  useEffect(() => {
    document.title = t('agents.documentTitle')
  }, [])

  const agentsQuery = useQuery<RawAgent[]>({
    queryKey: ['agents'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<AgentsList>('agents.list', {})
      return data.agents ?? []
    },
    refetchOnWindowFocus: false,
  })

  // agents.js:90 — load-failure toast (stable id so repeats dedupe).
  useEffect(() => {
    if (agentsQuery.isError) {
      const err = agentsQuery.error
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('agents.toastLoadFailed', { message }), { id: 'agents-load-err' })
    }
  }, [agentsQuery.isError, agentsQuery.error])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agents'] })

  // agents.js:224-240 — create; agent.exists → warn (not error).
  const createMutation = useMutation({
    mutationFn: (input: { id: string; name: string }) =>
      rpc.call('agents.create', buildCreatePayload(input)),
    onSuccess: (_data, input) => {
      toast.success(t('agents.toastCreated', { id: input.id.trim() }), { id: 'agents-create' })
      setDialog({ kind: 'none' })
      void invalidate()
    },
    onError: (err, input) => {
      const e = err as AgentsListError
      if (e.code === 'agent.exists') {
        toast.warning(t('agents.toastExists', { id: input.id.trim() }), { id: 'agents-create' })
      } else {
        toast.error(t('agents.toastCreateFailed', { message: e.message || String(err) }), {
          id: 'agents-create-err',
        })
      }
    },
  })

  // agents.js:426-462 — update; friendly messages for not_found / builtin_immutable.
  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; payload: Record<string, unknown> }) =>
      rpc.call('agents.update', vars.payload),
    onSuccess: (_data, vars) => {
      toast.success(t('agents.toastUpdated', { id: vars.id }), { id: 'agents-update' })
      setDialog({ kind: 'none' })
      void invalidate()
    },
    onError: (err, vars) => {
      const e = err as AgentsListError
      let friendly = t('agents.toastSaveFailed', { message: e.message || String(err) })
      if (e.code === 'agent.not_found') friendly = t('agents.toastNotFound', { id: vars.id })
      if (e.code === 'agent.builtin_immutable')
        friendly = t('agents.toastBuiltinImmutable', { id: vars.id })
      toast.error(friendly, { id: 'agents-update-err' })
    },
  })

  // agents.js:508-520 — delete after confirmation.
  const deleteMutation = useMutation({
    mutationFn: (id: string) => rpc.call('agents.delete', { id }),
    onSuccess: (_data, id) => {
      toast.success(t('agents.toastDeleted', { id }), { id: 'agents-delete' })
      setDialog({ kind: 'none' })
      void invalidate()
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('agents.toastDeleteFailed', { message }), { id: 'agents-delete-err' })
    },
  })

  const agents = agentsQuery.data ?? []
  const stats = agentStats(agents)
  const mutating = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  // agents.js:242-256 — Customize seeds the create dialog with `<id>-copy`.
  const openCustomize = (builtinId: string) => {
    setDialog({
      kind: 'create',
      seed: {
        ...EMPTY_FORM,
        id: (builtinId || 'main') + '-copy',
        name: t('agents.copyName', { id: builtinId }),
      },
    })
  }

  return (
    <div className="ag-stage">
      <header className="ag-stage__header">
        <div className="ag-stage__title-block">
          <span className="t-label">{t('agents.eyebrow')}</span>
          <h1 className="t-display">{t('agents.title')}</h1>
          <p className="ag-stage__subtitle">{t('agents.subtitle')}</p>
        </div>
        <div className="ag-stage__actions">
          <Button
            variant="outline"
            title={t('agents.refresh')}
            className="text-xs uppercase tracking-[0.14em]"
            onClick={() => void invalidate()}
          >
            <RefreshCwIcon />
            <span>{t('agents.refresh')}</span>
          </Button>
          <Button
            className="text-xs uppercase tracking-[0.14em]"
            onClick={() => setDialog({ kind: 'create', seed: { ...EMPTY_FORM } })}
          >
            <PlusIcon />
            <span>{t('agents.newAgent')}</span>
          </Button>
        </div>
      </header>

      <section className="ag-stats" aria-label={t('agents.statsLandmark')}>
        <StatTile
          label={t('agents.statTotal')}
          hero
          value={stats.total}
          hint={
            [
              stats.builtins ? t('agents.statBuiltinCount', { count: stats.builtins }) : '',
              stats.customs ? t('agents.statCustomCount', { count: stats.customs }) : '',
            ]
              .filter(Boolean)
              .join(' · ') || t('agents.statNoneConfigured')
          }
        />
        <StatTile
          label={t('agents.statModels')}
          value={stats.models || t('common.dash')}
          hint={stats.models ? t('agents.statModelsHint') : t('agents.statModelsUnset')}
        />
        <StatTile
          label={t('agents.statTools')}
          value={stats.tools}
          hint={t('agents.statToolsHint')}
        />
      </section>

      <section className="ag-list">
        <div className="ag-list__head">
          <h2 className="ag-list__title t-label">
            {t('agents.listTitle')}{' '}
            {agents.length ? <span className="ag-list__count t-data">{agents.length}</span> : null}
          </h2>
        </div>

        {agents.length === 0 ? (
          <div className="ag-empty">
            <div className="ag-empty__title">{t('agents.emptyTitle')}</div>
            <p className="ag-empty__msg">
              {t('agents.emptyMsgLead')} <strong>{t('agents.newAgent')}</strong>{' '}
              {/* The default agent id is an identifier, not copy — never translated. */}
              {t('agents.emptyMsgMiddle')} <code>{'main'}</code> {t('agents.emptyMsgTail')}
            </p>
          </div>
        ) : (
          <div className="ag-cards">
            <AnimatePresence initial={false}>
              {agents.map((agent, i) => (
                <MotionListItem key={String(agent.id || agent.name || i)}>
                  <AgentCard
                    agent={agent}
                    busy={mutating}
                    onChat={(id) => navigate('/chat?agent=' + encodeURIComponent(id))}
                    onEdit={(a) => setDialog({ kind: 'edit', seed: agentToForm(a) })}
                    onCustomize={openCustomize}
                    onDelete={(id) => setDialog({ kind: 'delete', id })}
                  />
                </MotionListItem>
              ))}
            </AnimatePresence>
          </div>
        )}
      </section>

      <AnimatePresence>
        {dialog.kind === 'create' || dialog.kind === 'edit' ? (
          <AgentDialog
            // Remount on a new seed so the form state resets when switching
            // between create / customize / a different agent's edit.
            key={dialog.kind + ':' + dialog.seed.id}
            mode={dialog.kind}
            seed={dialog.seed}
            saving={createMutation.isPending || updateMutation.isPending}
            onCancel={() => setDialog({ kind: 'none' })}
            onCreate={(id, name) => createMutation.mutate({ id, name })}
            onSave={(initial, current) => {
              const payload = buildUpdatePayload(initial, current)
              // agents.js:432-437 — no-op save: nothing changed → skip the RPC,
              // toast 'Nothing to save', and keep the dialog open.
              if (isNoOpUpdate(payload)) {
                toast.info(t('agents.toastNothingToSave'), { id: 'agents-update' })
                return
              }
              updateMutation.mutate({ id: current.id, payload })
            }}
          />
        ) : null}

        {dialog.kind === 'delete' ? (
          <ConfirmDialog
            title={t('agents.deleteTitle')}
            body={
              <>
                {t('agents.deleteBodyLead')} <strong>{dialog.id}</strong>
                {t('agents.deleteBodyTail')}
              </>
            }
            confirmLabel={t('agents.deleteConfirm')}
            busy={deleteMutation.isPending}
            onCancel={() => setDialog({ kind: 'none' })}
            onConfirm={() => deleteMutation.mutate(dialog.id)}
          />
        ) : null}
      </AnimatePresence>
    </div>
  )
}
