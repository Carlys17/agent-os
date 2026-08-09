import { lazy as reactLazy, Suspense, useEffect } from 'react'
import { type RouteObject, useLocation } from 'react-router'
import { t } from '@/i18n'
import { RouteErrorBoundary } from './RouteErrorBoundary'

type LazyRoute = NonNullable<RouteObject['lazy']>

interface ViewRoute {
  path: string
  title: string
  lazy: LazyRoute
}

const loadOverview: LazyRoute = async () => ({
  Component: (await import('@/views/overview/OverviewPage')).OverviewPage,
})
const loadHealth: LazyRoute = async () => ({
  Component: (await import('@/views/health/HealthPage')).HealthPage,
})
const loadChat: LazyRoute = async () => ({
  Component: (await import('@/views/chat/ChatPage')).ChatPage,
})
const loadSessions: LazyRoute = async () => ({
  Component: (await import('@/views/sessions/SessionsPage')).SessionsPage,
})
const loadAgents: LazyRoute = async () => ({
  Component: (await import('@/views/agents/AgentsPage')).AgentsPage,
})
const loadCron: LazyRoute = async () => ({
  Component: (await import('@/views/cron/CronPage')).CronPage,
})
const loadUsage: LazyRoute = async () => ({
  Component: (await import('@/views/usage/UsagePage')).UsagePage,
})
const loadSettings: LazyRoute = async () => ({
  Component: (await import('@/views/settings/SettingsPage')).SettingsPage,
})
const loadChannels: LazyRoute = async () => ({
  Component: (await import('@/views/channels/ChannelsPage')).ChannelsPage,
})
const loadMcp: LazyRoute = async () => ({
  Component: (await import('@/views/mcp/McpPage')).McpPage,
})
const loadApprovals: LazyRoute = async () => ({
  Component: (await import('@/views/approvals/ApprovalsPage')).ApprovalsPage,
})
const loadSkills: LazyRoute = async () => ({
  Component: (await import('@/views/skills/SkillsPage')).SkillsPage,
})
const loadLogs: LazyRoute = async () => ({
  Component: (await import('@/views/logs/LogsPage')).LogsPage,
})
const loadEnv: LazyRoute = async () => ({
  Component: (await import('@/views/env/EnvPage')).EnvPage,
})

// Titles resolve at module load. That is correct while the locale is chosen
// once at boot (see i18n/locale.ts); a future runtime locale switch would have
// to turn `title` into a getter.
const VIEW_ROUTES: ReadonlyArray<ViewRoute> = [
  { path: 'overview', title: t('shell.viewOverview'), lazy: loadOverview },
  { path: 'health', title: t('shell.viewHealth'), lazy: loadHealth },
  { path: 'chat', title: t('shell.viewChat'), lazy: loadChat },
  { path: 'sessions', title: t('shell.viewSessions'), lazy: loadSessions },
  { path: 'agents', title: t('shell.viewAgents'), lazy: loadAgents },
  { path: 'cron', title: t('shell.viewCron'), lazy: loadCron },
  { path: 'usage', title: t('shell.viewUsage'), lazy: loadUsage },
  { path: 'settings', title: t('shell.viewSettings'), lazy: loadSettings },
  { path: 'config', title: t('shell.viewConfig'), lazy: loadSettings },
  { path: 'setup', title: t('shell.viewSetup'), lazy: loadSettings },
  { path: 'channels', title: t('shell.viewChannels'), lazy: loadChannels },
  { path: 'mcp', title: t('shell.viewMcp'), lazy: loadMcp },
  { path: 'approvals', title: t('shell.viewApprovals'), lazy: loadApprovals },
  { path: 'skills', title: t('shell.viewSkills'), lazy: loadSkills },
  { path: 'env', title: t('shell.viewEnv'), lazy: loadEnv },
  { path: 'logs', title: t('shell.viewLogs'), lazy: loadLogs },
]

export const VIEWS: ReadonlyArray<{ path: string; title: string }> = VIEW_ROUTES.map(
  ({ path, title }) => ({ path, title }),
)

/**
 * Parity: js/router.js:32 — evaluated per resolve, not once at module load.
 * Mobile (<=768px) lands on chat, desktop on overview. Legacy re-reads
 * matchMedia inside `_resolve()` on every navigation, so a viewport change
 * that crosses the breakpoint before the index is (re)visited is honored.
 */
export function defaultViewPath(): string {
  try {
    return window.matchMedia('(max-width: 768px)').matches ? 'chat' : 'overview'
  } catch {
    return 'overview'
  }
}

// The index route must choose again whenever it is entered, so it cannot use a
// route.lazy function whose resolved module React Router caches. React.lazy
// still keeps both heavy views outside the entry bundle while preserving the
// legacy per-navigation desktop/mobile decision.
const IndexOverview = reactLazy(async () => ({
  default: (await import('@/views/overview/OverviewPage')).OverviewPage,
}))
const IndexChat = reactLazy(async () => ({
  default: (await import('@/views/chat/ChatPage')).ChatPage,
}))

function IndexView() {
  const Component = defaultViewPath() === 'chat' ? IndexChat : IndexOverview
  return (
    <Suspense fallback={<RoutePending />}>
      <Component />
    </Suspense>
  )
}

function NotFound() {
  // Parity: js/router.js:48-55 — path rendered as text, never HTML.
  // useLocation().pathname is basename-relative under react-router.
  const { pathname } = useLocation()
  useEffect(() => {
    document.title = t('shell.routeNotFoundTitle')
  }, [])
  return (
    <div className="p-8 text-muted-foreground">
      {t('shell.routeNotFoundBody', { path: pathname })}
    </div>
  )
}

function RoutePending() {
  return (
    <div className="p-8 text-muted-foreground" aria-hidden="true">
      {t('shell.routePending')}
    </div>
  )
}

function guarded(route: RouteObject): RouteObject {
  return {
    ...route,
    HydrateFallback: route.lazy ? RoutePending : undefined,
    errorElement: <RouteErrorBoundary />,
  }
}

export const routeChildren: RouteObject[] = [
  guarded({ index: true, Component: IndexView }),
  ...VIEW_ROUTES.map(({ path, lazy }) => guarded({ path, lazy })),
  guarded({ path: 'mcp/oauth/callback', lazy: loadMcp }),
  guarded({ path: '*', Component: NotFound }),
]
