import './channels.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useBlocker, useNavigate, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence } from 'motion/react'
import { CableIcon, PlusIcon, RefreshCwIcon, Settings2Icon } from 'lucide-react'
import { toast } from 'sonner'
import { CommandLine } from '@/components/CommandLine'
import { MotionListItem } from '@/lib/motion'
import { Button } from '@/components/ui/button'
import { useRpc } from '@/app/providers'
import { relTime } from '@/views/overview/logic'
import {
  loadSettingsSnapshot,
  SETTINGS_SNAPSHOT_QUERY_KEY,
  type SettingsSnapshot,
} from '@/views/settings/snapshot'
import { AdapterLogo } from './AdapterLogo'
import { ChannelSetupDialog } from './ChannelSetupDialog'
import {
  channelDisplay,
  channelStats,
  inactiveHint,
  isAccessLocked,
  mergeChannels,
  senderLabel,
  senderMeta,
  sortChannels,
  statusHint,
  type AccessAccount,
  type ChannelAccess,
  type MergedChannel,
  type RawChannel,
  type Tone,
} from './logic'

// channels.js:60-61 — the 5s reload cadence (react-query refetchInterval, the
// single source of truth alongside the channel.status event-driven invalidate).
const POLL_MS = 5000

// Channel health remains available even when the pairing endpoint fails.
interface ChannelsStatus {
  channels?: RawChannel[]
}
interface AccessList {
  channels?: ChannelAccess[]
}

// Tone token → tone-* class (status color ONLY via --tone; never hardcoded).
function toneClass(tone: Tone): string {
  return tone === 'danger' ? 'tone-danger' : tone === 'ok' ? 'tone-ok' : 'tone-dim'
}

function PersonRow({
  item,
  variant,
  disabled,
  onApprove,
  onDeny,
  onRevoke,
}: {
  item: AccessAccount
  variant: 'pending' | 'paired'
  disabled: boolean
  onApprove?: () => void
  onDeny?: () => void
  onRevoke?: () => void
}) {
  // Pending connections can be paired or denied; paired connections can be
  // disconnected. There are no account roles.
  return (
    <div className="ch-access__person">
      <div className="ch-access__identity">
        <strong>{senderLabel(item)}</strong>
        <span>{senderMeta(item)}</span>
      </div>
      {variant === 'pending' ? (
        <div className="ch-access__person-actions">
          <Button type="button" size="sm" disabled={disabled} onClick={onApprove}>
            Pair
          </Button>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={disabled}
            onClick={onDeny}
          >
            Deny
          </Button>
        </div>
      ) : (
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onRevoke}>
          Disconnect
        </Button>
      )}
    </div>
  )
}

function AccessPanel({
  channel,
  busy,
  onResolve,
  onRevoke,
}: {
  channel: MergedChannel
  busy: boolean
  onResolve: (channel: string, senderId: string, approved: boolean) => void
  onRevoke: (channel: string, senderId: string) => void
}) {
  // Telegram has one binary admission state: pending or paired.
  const access = channel.access
  if (!access || channel.type !== 'telegram') return null
  const channelName = String(channel.name || '')
  const pending = Array.isArray(access.pending) ? access.pending : []
  const paired = Array.isArray(access.paired) ? access.paired : []
  const locked = isAccessLocked(access.locked_until)

  return (
    <section className={`ch-access${pending.length ? ' ch-access--pending' : ''}`}>
      <div className="ch-access__head">
        <div>
          <span className="ch-access__eyebrow t-label">Telegram connections</span>
          <h3 className="ch-access__title">Pairing</h3>
        </div>
      </div>

      {locked ? (
        <p className="ch-access__warning">
          Pairing is locked for one hour after repeated invalid codes.
        </p>
      ) : null}

      <p className="ch-access__note">
        Direct messages always require pairing.{' '}
        {access.groups_enabled
          ? `${access.group_chat_ids?.length || 0} configured group(s) also require a paired sender${access.group_mention_required ? ' and a bot mention' : ''}.`
          : 'Group messaging is disabled.'}
      </p>
      <div className="ch-access__group">
        <div className="ch-access__group-title t-label">
          Pending pairing <span>{pending.length}</span>
        </div>
        {pending.length ? (
          <div className="ch-access__people">
            {pending.map((item, i) => (
              <PersonRow
                key={`pending-${String(item.sender_id ?? i)}`}
                item={item}
                variant="pending"
                disabled={busy}
                onApprove={() => onResolve(channelName, String(item.sender_id ?? ''), true)}
                onDeny={() => onResolve(channelName, String(item.sender_id ?? ''), false)}
              />
            ))}
          </div>
        ) : (
          <p className="ch-access__empty">No Telegram connections are waiting to pair.</p>
        )}
      </div>
      <div className="ch-access__group">
        <div className="ch-access__group-title t-label">
          Paired <span>{paired.length}</span>
        </div>
        {paired.length ? (
          <div className="ch-access__people">
            {paired.map((item, i) => (
              <PersonRow
                key={`paired-${String(item.sender_id ?? i)}`}
                item={item}
                variant="paired"
                disabled={busy}
                onRevoke={() => onRevoke(channelName, String(item.sender_id ?? ''))}
              />
            ))}
          </div>
        ) : (
          <p className="ch-access__empty">No paired Telegram connections yet.</p>
        )}
      </div>
    </section>
  )
}

function ChannelCard({
  channel,
  busy,
  configurationMode,
  onConfigure,
  onOpenAdvanced,
  onResolve,
  onRevoke,
}: {
  channel: MergedChannel
  busy: boolean
  configurationMode: 'loading' | 'guided' | 'advanced'
  onConfigure: () => void
  onOpenAdvanced: () => void
  onResolve: (channel: string, senderId: string, approved: boolean) => void
  onRevoke: (channel: string, senderId: string) => void
}) {
  // channels.js:202-241 — one channel card.
  const d = channelDisplay(channel)
  const since = channel.connected_since ? relTime(channel.connected_since) : '—'
  const hint = statusHint({
    status: d.status,
    isRunning: d.isRunning,
    isDead: d.isDead,
    enabled: channel.enabled !== false,
    name: d.name,
  })
  return (
    <article className={`ch-card ${toneClass(d.tone)}`} aria-label={`Channel ${d.name}`}>
      <header className="ch-card__head">
        <div className="ch-card__identity">
          <span className="ch-card__mark" aria-hidden="true">
            <AdapterLogo type={String(channel.type || '')} />
            <span
              className={`ch-card__dot tone-${d.tone === 'danger' ? 'danger' : d.tone === 'ok' ? 'ok' : 'dim'}`}
            />
          </span>
          <div>
            <span className="ch-card__name" title={d.name}>
              {d.name}
            </span>
            <span className="ch-card__type t-data">{channel.type || 'unknown'}</span>
          </div>
        </div>
        <div className="ch-card__head-actions">
          {configurationMode === 'guided' ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ch-card__configure"
              onClick={onConfigure}
            >
              <Settings2Icon />
              <span>Configure</span>
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ch-card__configure"
              disabled={configurationMode === 'loading'}
              onClick={onOpenAdvanced}
            >
              <Settings2Icon />
              <span>{configurationMode === 'loading' ? 'Loading…' : 'Advanced config'}</span>
            </Button>
          )}
          <span className={`ch-card__chip t-data ${toneClass(d.tone)}`}>{d.status}</span>
        </div>
      </header>
      <div className="ch-card__body">
        <dl className="ch-card__meta">
          <div>
            <dt className="t-label">Connected</dt>
            <dd className="t-data">{since}</dd>
          </div>
          <div>
            <dt className="t-label">Restart attempts</dt>
            <dd className="t-data">{d.attempts}</dd>
          </div>
        </dl>
        <p className="ch-card__hint">{hint}</p>
        <AccessPanel channel={channel} busy={busy} onResolve={onResolve} onRevoke={onRevoke} />
        <details className="ch-card__config">
          <summary>Adapter config</summary>
          <pre className="ch-card__config-pre t-data">{d.configJson}</pre>
        </details>
      </div>
    </article>
  )
}

function StatTile({
  label,
  value,
  hint,
  hero,
  attention,
}: {
  label: string
  value: React.ReactNode
  hint: React.ReactNode
  hero?: boolean
  attention?: boolean
}) {
  // channels.js:146,384-389 — the attention tile is warn-toned via
  // .ch-stat--attention (--warn), NOT a per-tile --tone; there is no danger
  // tone on a stat tile in the legacy contract.
  return (
    <div
      className={`ch-stat${hero ? ' ch-stat--hero' : ''}${attention ? ' ch-stat--attention' : ''}`}
      aria-label={label}
    >
      <span className="ch-stat__label t-label">{label}</span>
      <strong className="ch-stat__value t-data">{value}</strong>
      <span className="ch-stat__hint">{hint}</span>
    </div>
  )
}

export function ChannelsPage() {
  const rpc = useRpc()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const setupDirtyRef = useRef(false)
  const [setupResetVersion, setSetupResetVersion] = useState(0)
  const [setupDirty, setSetupDirty] = useState(false)
  const [setupSaveError, setSetupSaveError] = useState('')
  const setupOpen = searchParams.get('view') === 'setup'
  const editingName = searchParams.get('channel') || undefined

  useEffect(() => {
    document.title = 'Channels - AgentOS Control'
  }, [])

  // Load runtime status and Telegram pairing state in parallel.
  const channelsQuery = useQuery<MergedChannel[]>({
    queryKey: ['channels'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const [status, pairing] = await Promise.all([
        rpc.call<ChannelsStatus>('channels.status', {}),
        rpc
          .call<AccessList>('channels.pairing.list', {})
          .catch(() => ({ channels: [] }) as AccessList),
      ])
      return sortChannels(mergeChannels(status.channels, pairing.channels))
    },
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  })

  const setupSnapshotQuery = useQuery<SettingsSnapshot>({
    queryKey: SETTINGS_SNAPSHOT_QUERY_KEY,
    queryFn: () => loadSettingsSnapshot(rpc),
    refetchOnWindowFocus: false,
  })

  // channels.js:107 — load-failure toast (stable id so repeats dedupe).
  useEffect(() => {
    if (channelsQuery.isError) {
      const err = channelsQuery.error
      const message = err instanceof Error ? err.message : String(err)
      toast.error('Failed to load channels: ' + message, { id: 'channels-load-err' })
    }
  }, [channelsQuery.isError, channelsQuery.error])

  // channels.js:55-56,64-72 — subscribe to real-time channel.status events and
  // invalidate the channels query (targeted refetch); cleaned up on unmount.
  useEffect(() => {
    const unsub = rpc.on('channel.status', () => {
      void queryClient.invalidateQueries({ queryKey: ['channels'] })
    })
    return () => {
      unsub()
    }
  }, [rpc, queryClient])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['channels'] })

  const updateSetupDirty = useCallback((dirty: boolean) => {
    setupDirtyRef.current = dirty
    setSetupDirty(dirty)
  }, [])

  const openSetup = (channelName?: string) => {
    setSetupSaveError('')
    updateSetupDirty(false)
    setSetupResetVersion((version) => version + 1)
    const next = new URLSearchParams(searchParams)
    next.set('view', 'setup')
    if (channelName) next.set('channel', channelName)
    else next.delete('channel')
    setSearchParams(next)
  }

  const closeSetup = ({ reset = false }: { reset?: boolean } = {}) => {
    if (reset) {
      updateSetupDirty(false)
      setSetupSaveError('')
      setSetupResetVersion((version) => version + 1)
    }
    const next = new URLSearchParams(searchParams)
    next.delete('view')
    next.delete('channel')
    setSearchParams(next, { replace: true })
  }

  const setupNavigationBlocker = useBlocker(() => setupDirtyRef.current)
  const setupNavigationBlockerRef = useRef(setupNavigationBlocker)
  useEffect(() => {
    setupNavigationBlockerRef.current = setupNavigationBlocker
  }, [setupNavigationBlocker])

  interface ChannelSaveResult {
    restartRequired?: boolean
    warnings?: string[]
  }

  const channelSetupMutation = useMutation({
    mutationFn: async ({
      entry,
      expectedRevision,
    }: {
      entry: Record<string, unknown>
      expectedRevision?: string
    }) => {
      await rpc.call('onboarding.channel.probe', { entry })
      return await rpc.call<ChannelSaveResult>('onboarding.channel.upsert', {
        entry,
        ...(expectedRevision ? { expectedRevision } : {}),
      })
    },
    onMutate: () => setSetupSaveError(''),
    onSuccess: async (result) => {
      updateSetupDirty(false)
      await Promise.all([
        invalidate(),
        queryClient.invalidateQueries({ queryKey: SETTINGS_SNAPSHOT_QUERY_KEY }),
      ])
      toast.success(
        result.restartRequired
          ? 'Channel saved. Restart AgentOS to activate it.'
          : 'Channel saved.',
        { id: 'channels-setup-save' },
      )
      if (setupNavigationBlockerRef.current.state === 'blocked') {
        setSetupSaveError('')
        setSetupResetVersion((version) => version + 1)
        setupNavigationBlockerRef.current.proceed()
      } else {
        closeSetup({ reset: true })
      }
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : String(error)
      const conflict = message.includes('config revision mismatch')
      setSetupSaveError(
        conflict
          ? 'Configuration changed elsewhere. Reload this setup, then review your draft.'
          : `Channel could not be saved: ${message}`,
      )
      if (conflict) void setupSnapshotQuery.refetch()
      toast.error(conflict ? 'Channel draft needs a fresh configuration.' : message, {
        id: 'channels-setup-save-error',
      })
    },
  })

  const discardBlockedNavigation = () => {
    if (setupNavigationBlocker.state !== 'blocked') return
    updateSetupDirty(false)
    setSetupSaveError('')
    setSetupResetVersion((version) => version + 1)
    setupNavigationBlocker.proceed()
  }

  const keepBlockedNavigation = () => {
    if (setupNavigationBlocker.state === 'blocked') setupNavigationBlocker.reset()
  }

  // Pair or deny one pending connection.
  const resolveMutation = useMutation({
    mutationFn: (vars: { channel: string; senderId: string; approved: boolean }) =>
      rpc.call(vars.approved ? 'channels.pairing.approve' : 'channels.pairing.deny', {
        channel: vars.channel,
        senderId: vars.senderId,
      }),
    onSuccess: (_data, vars) => {
      if (vars.approved) toast.info('Telegram connection paired.', { id: 'channels-resolve' })
      else toast.warning('Telegram pairing denied.', { id: 'channels-resolve' })
      void invalidate()
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error('Failed to resolve pairing request: ' + message, { id: 'channels-resolve-err' })
    },
  })

  // Disconnect one paired Telegram sender.
  const revokeMutation = useMutation({
    mutationFn: (vars: { channel: string; senderId: string }) =>
      rpc.call('channels.pairing.revoke', vars),
    onSuccess: () => {
      toast.info('Telegram connection disconnected.', { id: 'channels-revoke' })
      void invalidate()
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error('Failed to disconnect Telegram: ' + message, { id: 'channels-revoke-err' })
    },
  })

  const busy = resolveMutation.isPending || revokeMutation.isPending

  const channels = channelsQuery.data ?? []
  const stats = channelStats(channels)
  const guidedChannelTypes = new Set(
    (setupSnapshotQuery.data?.catalog?.channels || []).map((spec) => spec.type),
  )

  const onResolve = (channel: string, senderId: string, approved: boolean) =>
    resolveMutation.mutate({ channel, senderId, approved })
  const onRevoke = (channel: string, senderId: string) =>
    revokeMutation.mutate({ channel, senderId })

  return (
    <div className="ch-stage">
      <header className="ch-stage__header">
        <div className="ch-stage__title-block">
          <span className="t-label">Control · Channels</span>
          <h1 className="t-display">Channels</h1>
          <p className="ch-stage__subtitle">
            Add messaging adapters, monitor runtime health, and pair Telegram connections.
          </p>
        </div>
        <div className="ch-stage__actions">
          <Button
            variant="outline"
            title="Refresh"
            className="ch-stage__refresh text-xs uppercase tracking-[0.14em]"
            disabled={channelsQuery.isFetching}
            onClick={() => void invalidate()}
          >
            <RefreshCwIcon className={channelsQuery.isFetching ? 'ch-refresh-spin' : undefined} />
            <span>{channelsQuery.isFetching ? 'Refreshing…' : 'Refresh'}</span>
          </Button>
          <Button type="button" className="ch-stage__add" onClick={() => openSetup()}>
            <PlusIcon />
            <span>Add channel</span>
          </Button>
        </div>
      </header>

      <section
        className={`ch-command${channelsQuery.isFetching ? ' is-loading' : ''}`}
        aria-label="Channel operations"
        aria-busy={channelsQuery.isFetching}
      >
        <div className="ch-command__toolbar">
          <div className="ch-command__heading">
            <span className="ch-command__icon" aria-hidden="true">
              <CableIcon />
            </span>
            <div>
              <span className="t-label">Integration mesh</span>
              <strong>Channel posture</strong>
            </div>
          </div>
          <span className="ch-command__cadence t-data">
            <span aria-hidden="true" /> Live · refreshes every 5s
          </span>
        </div>
        <div className="ch-stats" aria-label="Channels summary">
          <StatTile
            label="Total channels"
            hero
            value={stats.total}
            hint={`${stats.typeCount} type${stats.typeCount === 1 ? '' : 's'} configured`}
          />
          <StatTile
            label="Connected"
            value={stats.connected}
            hint={
              stats.connected
                ? 'live now'
                : stats.attention
                  ? `${stats.attention} unhealthy`
                  : 'all idle'
            }
          />
          <StatTile
            label="Inactive"
            value={stats.inactive}
            hint={
              stats.attention ? (
                // channels.js:139 — legacy wraps this hint in .ch-neg (--danger).
                <span className="ch-neg">{stats.attention} need attention</span>
              ) : (
                inactiveHint(stats.inactive, stats.disabled)
              )
            }
          />
          <StatTile label="Restart attempts" value={stats.restarts} hint="since gateway start" />
          <StatTile
            label="Pairing requests"
            value={stats.pendingAccess}
            attention={stats.pendingAccess > 0}
            hint={stats.pendingAccess ? 'Telegram connections waiting' : 'nothing waiting'}
          />
        </div>
      </section>

      <section className="ch-list">
        <div className="ch-list__head">
          <div>
            <h2 className="ch-list__title">Configured channels</h2>
            <p className="ch-list__description">
              Runtime adapters, connection health, and Telegram pairing in one place.
            </p>
          </div>
          <div className="ch-list__actions">
            {channels.length ? (
              <span className="ch-list__count t-data">
                {channels.length} channel{channels.length === 1 ? '' : 's'}
              </span>
            ) : null}
          </div>
        </div>

        {channels.length === 0 ? (
          <div className="ch-empty">
            <div className="ch-empty__title">No configured channels.</div>
            <p className="ch-empty__msg">
              Connect Telegram, Slack, Discord, or another adapter here. AgentOS validates the
              configuration before saving and keeps credentials write-only.
            </p>
            <div className="ch-empty__actions">
              <Button type="button" onClick={() => openSetup()}>
                <PlusIcon />
                <span>Add your first channel</span>
              </Button>
            </div>
            <div className="ch-empty__commands">
              <CommandLine
                command="agentos onboard configure channels"
                toastIdPrefix="channels-copy"
              />
              <CommandLine command="agentos channels list" toastIdPrefix="channels-copy" />
            </div>
          </div>
        ) : (
          <div className="ch-cards">
            <AnimatePresence initial={false}>
              {channels.map((channel, i) => {
                const type = String(channel.type || '')
                const configurationMode = setupSnapshotQuery.isLoading
                  ? 'loading'
                  : guidedChannelTypes.has(type)
                    ? 'guided'
                    : 'advanced'
                return (
                  <MotionListItem key={String(channel.name || channel.id || i)}>
                    <ChannelCard
                      channel={channel}
                      busy={busy}
                      configurationMode={configurationMode}
                      onConfigure={() => openSetup(String(channel.name || ''))}
                      onOpenAdvanced={() => navigate('/config')}
                      onResolve={onResolve}
                      onRevoke={onRevoke}
                    />
                  </MotionListItem>
                )
              })}
            </AnimatePresence>
          </div>
        )}
      </section>

      <ChannelSetupDialog
        key={`${editingName || 'new'}:${setupResetVersion}:${setupSnapshotQuery.data ? 'ready' : 'loading'}`}
        open={setupOpen}
        editingName={editingName}
        snapshot={setupSnapshotQuery.data}
        runtimeChannels={channels}
        loading={setupSnapshotQuery.isLoading}
        loadError={
          setupSnapshotQuery.isError
            ? setupSnapshotQuery.error instanceof Error
              ? setupSnapshotQuery.error.message
              : String(setupSnapshotQuery.error)
            : undefined
        }
        saving={channelSetupMutation.isPending}
        saveError={setupSaveError}
        onRetry={() => void setupSnapshotQuery.refetch()}
        onSave={(entry, expectedRevision) =>
          channelSetupMutation.mutate({ entry, expectedRevision })
        }
        onClose={() => closeSetup()}
        onDiscard={() => closeSetup({ reset: true })}
        navigationBlocked={setupNavigationBlocker.state === 'blocked'}
        onKeepNavigation={keepBlockedNavigation}
        onDiscardNavigation={discardBlockedNavigation}
        onResolveConflict={() => setSetupSaveError('')}
        onOpenAdvanced={() => navigate('/config')}
        onDirtyChange={updateSetupDirty}
      />
      <span className="sr-only" aria-live="polite">
        {setupDirty ? 'Channel setup has unsaved changes.' : ''}
      </span>
    </div>
  )
}
