import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { SkillsPage } from './SkillsPage'
import bankrSymbolUrl from '@/assets/bankr-symbol.svg'
import capminalSymbolUrl from '@/assets/capminal-symbol.svg'
import robinhoodSymbolUrl from '@/assets/robinhood-symbol.png'

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}))

type Handler = (...args: unknown[]) => void
function makeRpc() {
  const listeners = new Map<string, Set<Handler>>()
  return {
    waitForConnection: vi.fn().mockResolvedValue(undefined),
    call: vi.fn(),
    on: vi.fn((event: string, handler: Handler) => {
      if (!listeners.has(event)) listeners.set(event, new Set())
      listeners.get(event)!.add(handler)
      return () => listeners.get(event)?.delete(handler)
    }),
    emit(event: string, ...args: unknown[]) {
      listeners.get(event)?.forEach((h) => h(...args))
    },
  }
}
let mockRpc = makeRpc()

vi.mock('@/app/providers', () => ({
  useRpc: () => mockRpc,
  useBootstrap: () => ({
    version: '1',
    ws_url: 'ws://127.0.0.1:18791/ws',
    auth_mode: 'none',
    base_path: '/control',
    config_path: '/tmp/agentos.toml',
    features: {},
  }),
}))

const READY_MANAGED = {
  name: 'trader',
  description: 'Trades things',
  layer: 'managed',
  acquisition: {
    kind: 'hub',
    source_id: 'clawhub',
    identifier: 'uniswap-swap',
    removable: true,
    updatable: true,
  },
  publisher: { id: '', name: '', url: '', logo: '' },
  availability: { offered: true, reason: '', detail: '' },
  status: 'ready',
  emoji: '📈',
}
const NEEDS_BUNDLED = {
  name: 'weather',
  description: 'Weather lookups',
  layer: 'bundled',
  acquisition: { kind: 'shipped', removable: false, updatable: false },
  publisher: { id: '', name: '', url: '', logo: '' },
  availability: {
    offered: false,
    reason: 'ineligible',
    detail: 'Installed, but not offered to the agent: the binary curl is not on PATH.',
  },
  status: 'needs_setup',
  missing_bins: ['curl'],
  install: [{ id: 'brew-curl', kind: 'brew', label: 'Install curl', bins: ['curl'] }],
}
// A hub install the gateway will not offer to remove: `skills.uninstall` only
// deletes from the configured managed dir, and this one is recorded elsewhere.
const STRANDED_HUB = {
  name: 'stranded',
  description: 'Installed from a hub AgentOS can no longer delete from.',
  layer: 'managed',
  acquisition: {
    kind: 'hub',
    source_id: 'clawhub',
    identifier: 'stranded-skill',
    removable: false,
    updatable: true,
  },
  status: 'ready',
}
// Hand-copied into the managed directory: same `layer`, no lockfile entry, so
// neither affordance applies. Grouping and buttons must follow acquisition.
const LOCAL_IN_MANAGED = {
  name: 'handrolled',
  description: 'Copied in by hand',
  layer: 'managed',
  acquisition: { kind: 'local', removable: false, updatable: false },
  status: 'ready',
}
const BANKR_HUB_SKILL = {
  name: 'bankr-swaps',
  description: 'Swap tokens through Bankr.',
  layer: 'managed',
  acquisition: { kind: 'hub', source_id: 'bankr', identifier: 'bankr-swaps', removable: true },
  publisher: { id: 'bankr', name: 'Bankr', url: 'https://bankr.bot', logo: '' },
  status: 'ready',
}
// Ready, eligible, and still never reaching the model.
const WITHHELD_SKILL = {
  name: 'quiet',
  description: 'The agent is never told about this one.',
  layer: 'bundled',
  acquisition: { kind: 'shipped' },
  status: 'ready',
  eligible: true,
  availability: {
    offered: false,
    reason: 'model_invocation_disabled',
    detail: 'This skill declares disable_model_invocation, so the agent is never offered it.',
  },
}
const CATALOG_ITEM = {
  name: 'Uniswap',
  identifier: 'uniswap-swap',
  provider: 'Uniswap',
  source: 'clawhub',
  logo: 'https://raw.githubusercontent.com/BankrBot/skills/main/uniswap/uniswap.svg',
  description: 'DEX swaps',
  category: 'defi',
  demo: { code: 'swap(1, ETH)', language: 'python', title: 'Quote a swap' },
}
const BANKR_CATALOG_ITEM = {
  name: 'bankr-token-scam-analysis',
  identifier: 'bankr-token-scam-analysis',
  provider: 'BankrBot',
  source: 'bankr',
  description: 'Analyze token risk.',
}
const CAPMINAL_CATALOG_ITEM = {
  name: 'morse-launch-b20',
  identifier: 'https://github.com/Capminal/agent-skills/tree/main/morse-launch-b20',
  provider: 'Capminal',
  source: 'capminal',
  description: 'Morse launch B20 skill.',
}
// A needs_setup skill carrying both a Requirements manifest and Missing bins/env
// (skills.js:743-777,792-803). requirements.items exercises the ready /
// needs_setup / missing_skill status branches plus the missing + requires detail.
const REQ_BUNDLED = {
  name: 'oracle',
  description: 'On-chain oracle reads',
  layer: 'bundled',
  status: 'needs_setup',
  missing_bins: ['jq'],
  missing_env: ['ORACLE_KEY'],
  requirements: {
    items: [
      {
        name: 'jq',
        status: 'needs_setup',
        missing_bins: ['jq'],
      },
      {
        name: 'apikey',
        status: 'missing_skill',
        requires_env: ['ORACLE_KEY'],
      },
      {
        name: 'python',
        status: 'ready',
        requires_bins: ['python3'],
      },
    ],
  },
}

// Partner identity comes from the server-side publisher allowlist, never from
// the `robinhood-` name prefix — the client no longer reads the name at all.
const ROBINHOOD_READY = {
  name: 'robinhood-rwa-addresses',
  description: 'Look up tokenized-stock contract addresses.',
  layer: 'bundled',
  acquisition: { kind: 'shipped' },
  publisher: { id: 'robinhood', name: 'Robinhood', url: 'https://robinhood.com', logo: '' },
  status: 'ready',
}

const ROBINHOOD_UNDECLARED = {
  name: 'robinhood-agentic-trading',
  description: 'Operate Robinhood Agentic Trading through the Robinhood Trading MCP.',
  layer: 'bundled',
  acquisition: { kind: 'shipped' },
  publisher: { id: 'robinhood', name: 'Robinhood', url: 'https://robinhood.com', logo: '' },
  status: 'not_declared',
}

// A catalog row the empty-query browse does NOT return — the case where the
// installed row used to vanish the moment the search was cleared.
const SEARCH_ONLY_ITEM = {
  name: 'Ledger Watch',
  identifier: 'ledger-watch',
  provider: 'Ledger',
  source: 'clawhub',
  description: 'Watch a ledger address.',
}

function wireRpc(
  opts: {
    skills?: unknown[]
    skillsSequence?: unknown[][]
    listPromise?: Promise<unknown>
    listReject?: boolean
    searchResults?: unknown[]
    /**
     * The catalog's own answer to a query. The mock used to return the same
     * rows for every call, which is exactly why a list that swaps on the query
     * text could break without a test noticing.
     */
    search?: (query: string, source: string) => unknown[] | Promise<{ results: unknown[] }>
    installResponse?: Record<string, unknown>
    uninstallResponse?: Record<string, unknown>
    updateResponse?: Record<string, unknown>
    depsResponse?: Record<string, unknown>
  } = {},
) {
  let listIndex = 0
  mockRpc.call.mockImplementation((method: string, params?: unknown) => {
    const p = (params ?? {}) as { query?: string; source?: string }
    switch (method) {
      case 'skills.list':
        if (opts.listPromise) return opts.listPromise
        if (opts.skillsSequence) {
          const index = Math.min(listIndex, opts.skillsSequence.length - 1)
          listIndex += 1
          return Promise.resolve({ skills: opts.skillsSequence[index] ?? [] })
        }
        return opts.listReject
          ? Promise.reject(new Error('list down'))
          : Promise.resolve({ skills: opts.skills ?? [READY_MANAGED, NEEDS_BUNDLED] })
      case 'skills.search': {
        const query = (p.query ?? '').trim()
        const source = p.source ?? ''
        if (opts.search) {
          const answer = opts.search(query, source)
          return Array.isArray(answer) ? Promise.resolve({ results: answer }) : answer
        }
        const all = (opts.searchResults ?? [CATALOG_ITEM]) as Record<string, unknown>[]
        const scoped = source ? all.filter((r) => r.source === source) : all
        const q = query.toLowerCase()
        const results = q
          ? scoped.filter((r) =>
              [r.name, r.description, r.provider].some((f) =>
                String(f ?? '')
                  .toLowerCase()
                  .includes(q),
              ),
            )
          : scoped
        return Promise.resolve({ results })
      }
      case 'skills.install':
        return Promise.resolve(opts.installResponse ?? { success: true, name: 'uniswap-swap' })
      case 'skills.uninstall':
        return Promise.resolve(opts.uninstallResponse ?? { success: true })
      case 'skills.update':
        return Promise.resolve(opts.updateResponse ?? { results: [{ success: true }] })
      case 'skills.deps.install':
        return Promise.resolve(opts.depsResponse ?? { success: true, missing_still: {} })
      default:
        return Promise.resolve({})
    }
  })
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderPage(client: QueryClient = makeClient()) {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <SkillsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

/** The <details> block whose heading is `label`, i.e. one Installed group. */
function groupNamed(label: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: label })
  const block = heading.closest('details')
  expect(block).not.toBeNull()
  return block as HTMLElement
}

const callsFor = (m: string) => mockRpc.call.mock.calls.filter(([x]) => x === m)

describe('SkillsPage', () => {
  beforeEach(() => {
    mockRpc = makeRpc()
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    vi.mocked(toast.info).mockClear()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls skills.list after waitForConnection and groups installed cards by provenance', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(mockRpc.call).toHaveBeenCalledWith('skills.list', {}))
    expect(mockRpc.waitForConnection).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    expect(screen.getByLabelText('Skill weather')).toBeInTheDocument()
    // Provenance groups: shipped before hub (SKILL_GROUP_ORDER), not layers.
    expect(screen.getByText('Shipped with AgentOS')).toBeInTheDocument()
    expect(screen.getByText('Installed from a hub')).toBeInTheDocument()
  })

  it('renders the status metric pills from the payload', async () => {
    wireRpc()
    renderPage()
    // 1 ready, 1 needs_setup, total 2
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Filter: All' })).toHaveTextContent('2'),
    )
    expect(screen.getByRole('button', { name: 'Filter: Ready' })).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'Filter: Needs setup' })).toHaveTextContent('1')
  })

  it('renders an accessible source navigator with the official partner logos', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.getAttribute('aria-label'))).toEqual([
      'Installed',
      'Bankr',
      'Capminal',
      'Robinhood',
      'Community',
    ])
    expect(
      within(screen.getByRole('tab', { name: 'Bankr' }))
        .getByRole('presentation')
        .getAttribute('src'),
    ).toBe(bankrSymbolUrl)
    expect(
      within(screen.getByRole('tab', { name: 'Capminal' }))
        .getByRole('presentation')
        .getAttribute('src'),
    ).toBe(capminalSymbolUrl)
    expect(
      within(screen.getByRole('tab', { name: 'Robinhood' }))
        .getByRole('presentation')
        .getAttribute('src'),
    ).toBe(robinhoodSymbolUrl)
  })

  it('supports arrow-key navigation across skill sources', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())

    const installed = screen.getByRole('tab', { name: 'Installed' })
    installed.focus()
    fireEvent.keyDown(installed, { key: 'ArrowRight' })

    const bankr = screen.getByRole('tab', { name: 'Bankr' })
    expect(bankr).toHaveAttribute('aria-selected', 'true')
    expect(bankr).toHaveFocus()

    fireEvent.keyDown(bankr, { key: 'ArrowRight' })
    const capminal = screen.getByRole('tab', { name: 'Capminal' })
    expect(capminal).toHaveAttribute('aria-selected', 'true')
    expect(capminal).toHaveFocus()
  })

  it('the status pill filters the installed list', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill weather')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Filter: Ready' }))
    await waitFor(() => expect(screen.queryByLabelText('Skill weather')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Skill trader')).toBeInTheDocument()
  })

  it('the header filter searches name/description', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Filter installed skills'), {
      target: { value: 'weather' },
    })
    await waitFor(() => expect(screen.queryByLabelText('Skill trader')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Skill weather')).toBeInTheDocument()
  })

  it('toasts when skills.list fails', async () => {
    wireRpc({ listReject: true })
    renderPage()
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
  })

  // ── Registry search debounce (skills.js:210-220, 250ms) ──────────────────
  // Only the FINAL keystroke reaches the server, and it does so exactly once:
  // rapid typing coalesces to a single skills.search for the settled value.
  it('community search fires skills.search once after the debounce interval', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    // snapshot fetch (query:'') fires on tab entry
    const input = await screen.findByLabelText('Search community skills')
    const searchesFor = (q: string) =>
      callsFor('skills.search').filter(([, p]) => (p as { query?: string })?.query === q)
    // Type three quick keystrokes.
    fireEvent.change(input, { target: { value: 'u' } })
    fireEvent.change(input, { target: { value: 'un' } })
    fireEvent.change(input, { target: { value: 'uni' } })
    // The debounced search for the settled value fires exactly once.
    await waitFor(() => expect(searchesFor('uni')).toHaveLength(1))
    // The intermediate keystrokes never reached the server.
    expect(searchesFor('u')).toHaveLength(0)
    expect(searchesFor('un')).toHaveLength(0)
  })

  it('loads registry logos without sending the operator page as a referrer', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))

    const card = await screen.findByLabelText('Catalog skill Uniswap')
    const logo = within(card).getByRole('presentation')

    expect(logo).toHaveAttribute('src', CATALOG_ITEM.logo)
    expect(logo).toHaveAttribute('referrerpolicy', 'no-referrer')
  })

  it('uses the official Bankr icon when a Bankr catalog item has no logo metadata', async () => {
    wireRpc({ searchResults: [BANKR_CATALOG_ITEM] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: 'Bankr' }))

    const card = await screen.findByLabelText('Catalog skill bankr-token-scam-analysis')
    expect(within(card).getByRole('presentation')).toHaveAttribute('src', bankrSymbolUrl)
  })

  it('uses the official Capminal icon when a Capminal catalog item has no logo metadata', async () => {
    wireRpc({ searchResults: [CAPMINAL_CATALOG_ITEM] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: 'Capminal' }))

    const card = await screen.findByLabelText('Catalog skill morse-launch-b20')
    expect(within(card).getByRole('presentation')).toHaveAttribute('src', capminalSymbolUrl)
  })

  // ── Install (per-item busy, correct RPC + params + invalidation) ─────────
  it('installing a catalog skill calls skills.install with identifier/source/force and reloads', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const card = await screen.findByLabelText('Catalog skill Uniswap')
    fireEvent.click(within(card).getByRole('button', { name: /^Install$/i }))
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.install', {
        identifier: 'uniswap-swap',
        source: 'clawhub',
        force: false,
      }),
    )
    await waitFor(() => expect(toast.success).toHaveBeenCalled())
    // success invalidates skills.list (a reload)
    await waitFor(() => expect(callsFor('skills.list').length).toBeGreaterThanOrEqual(2))
  })

  it('a dangerous scan verdict arms a force install instead of erroring', async () => {
    wireRpc({
      installResponse: {
        success: false,
        scan_verdict: 'dangerous',
        scan_findings: [1, 2],
        name: 'Uniswap',
      },
    })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const card = await screen.findByLabelText('Catalog skill Uniswap')
    fireEvent.click(within(card).getByRole('button', { name: /^Install$/i }))
    // Button re-arms to "Force install"; the second click sends force:true.
    const force = await within(card).findByRole('button', { name: /Force install/i })
    fireEvent.click(force)
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.install', {
        identifier: 'uniswap-swap',
        source: 'clawhub',
        force: true,
      }),
    )
  })

  // ── Update / Uninstall from the installed-skill dialog ───────────────────
  it('a managed skill dialog updates via skills.update and reloads', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill trader'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^Update$/i }))
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.update', { name: 'trader' }),
    )
    await waitFor(() => expect(callsFor('skills.list').length).toBeGreaterThanOrEqual(2))
  })

  it('a managed skill dialog removes via skills.uninstall and closes', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill trader'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^Remove$/i }))
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.uninstall', { name: 'trader' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('bundled (non-managed) skill dialog has no Update/Remove', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill weather')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill weather'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('button', { name: /^Update$/i })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /^Remove$/i })).not.toBeInTheDocument()
  })

  // ── deps.install prompt → confirm → deps.install ─────────────────────────
  it('the install-deps button in a skill dialog calls skills.deps.install with name + install_id', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill weather')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill weather'))
    const dialog = await screen.findByRole('dialog')
    // The install option surfaces because missing_bins is non-empty.
    fireEvent.click(within(dialog).getByRole('button', { name: /Install via brew/i }))
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.deps.install', {
        name: 'weather',
        install_id: 'brew-curl',
      }),
    )
    // Nothing still missing → the dialog closes.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('deps.install that leaves deps missing keeps the dialog open', async () => {
    wireRpc({ depsResponse: { success: true, missing_still: { bins: ['curl'] } } })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill weather')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill weather'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /Install via brew/i }))
    await waitFor(() =>
      expect(mockRpc.call).toHaveBeenCalledWith('skills.deps.install', expect.anything()),
    )
    // Still missing → dialog stays open.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // ── Robinhood empty state ────────────────────────────────────────────────
  it('the Robinhood tab shows the empty state when no robinhood skills are installed', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))
    expect(await screen.findByText(/Robinhood skills are on the way/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Search Robinhood skills')).toBeInTheDocument()
  })

  it('gives Robinhood the Bankr catalog shell while preserving installed-skill actions', async () => {
    wireRpc({ skills: [ROBINHOOD_UNDECLARED, ROBINHOOD_READY] })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))

    const readyCard = await screen.findByLabelText('Robinhood skill robinhood-rwa-addresses')
    const tradingCard = screen.getByLabelText('Robinhood skill robinhood-agentic-trading')
    expect(readyCard).toHaveClass('sk-rcard', 'sk-rcard--partner')
    expect(readyCard.closest('.sk-grid')).toHaveClass('sk-grid--registry')
    expect(within(readyCard).getByRole('presentation')).toHaveAttribute('src', robinhoodSymbolUrl)
    expect(within(readyCard).getByText('Robinhood')).toBeInTheDocument()
    // The source label is the row's real acquisition now, not a hardcoded
    // 'bundled' — a partner hub install lands in this same tab.
    expect(within(readyCard).getByText('shipped')).toBeInTheDocument()
    expect(within(readyCard).getByText('Ready')).toBeInTheDocument()
    expect(within(tradingCard).getByText('No manifest')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Install$/i })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search Robinhood skills'), {
      target: { value: 'addresses' },
    })
    await waitFor(() =>
      expect(
        screen.queryByLabelText('Robinhood skill robinhood-agentic-trading'),
      ).not.toBeInTheDocument(),
    )
    expect(screen.getByLabelText('Robinhood skill robinhood-rwa-addresses')).toBeInTheDocument()
    expect(callsFor('skills.search')).toHaveLength(0)

    fireEvent.change(screen.getByLabelText('Search Robinhood skills'), {
      target: { value: '   ' },
    })
    await waitFor(() =>
      expect(
        screen.getByLabelText('Robinhood skill robinhood-agentic-trading'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByLabelText('Robinhood skill robinhood-rwa-addresses')).toBeInTheDocument()

    fireEvent.click(
      within(readyCard).getByRole('button', {
        name: 'View details for robinhood-rwa-addresses',
      }),
    )
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('filters Robinhood status locally without changing the partner catalog contract', async () => {
    wireRpc({ skills: [ROBINHOOD_UNDECLARED, ROBINHOOD_READY] })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))
    await screen.findByLabelText('Robinhood skill robinhood-rwa-addresses')

    fireEvent.click(screen.getByRole('button', { name: 'Filter Robinhood skills: Ready' }))
    expect(screen.getByLabelText('Robinhood skill robinhood-rwa-addresses')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.queryByLabelText('Robinhood skill robinhood-agentic-trading'),
      ).not.toBeInTheDocument(),
    )
    expect(callsFor('skills.search')).toHaveLength(0)
  })

  it('keeps an active zero-count Robinhood status visible after refresh', async () => {
    wireRpc({
      skillsSequence: [[ROBINHOOD_UNDECLARED, ROBINHOOD_READY], [ROBINHOOD_UNDECLARED]],
    })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))
    await screen.findByLabelText('Robinhood skill robinhood-rwa-addresses')
    fireEvent.click(screen.getByRole('button', { name: 'Filter Robinhood skills: Ready' }))

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    const readyFilter = await screen.findByRole('button', {
      name: 'Filter Robinhood skills: Ready',
    })
    await waitFor(() => expect(readyFilter).toHaveTextContent('Ready 0'))
    expect(readyFilter).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('No Robinhood skills are ready.')).toBeInTheDocument()
  })

  it('shows a Robinhood skeleton instead of a false empty state while skills load', async () => {
    wireRpc({ listPromise: new Promise(() => undefined) })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))

    expect(
      await screen.findByRole('status', { name: 'Loading Robinhood skills' }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Robinhood skills are on the way/i)).not.toBeInTheDocument()
  })

  it('shows the skills load failure inside the Robinhood source panel', async () => {
    wireRpc({ listReject: true })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Robinhood/i }))

    expect(await screen.findByText(/Failed to load: Error: list down/i)).toBeInTheDocument()
    expect(screen.queryByText(/Robinhood skills are on the way/i)).not.toBeInTheDocument()
  })

  // ── SK1: Requirements + Missing sections in the installed-skill dialog ────
  // (skills.js:743-777,792-803,805,854-855)
  it('the installed-skill dialog renders the Requirements section and Missing bins/env for a needs_setup skill', async () => {
    wireRpc({ skills: [REQ_BUNDLED] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill oracle')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill oracle'))
    const dialog = await screen.findByRole('dialog')

    // Requirements section: heading + one row per requirement item.
    expect(within(dialog).getByText('Requirements')).toBeInTheDocument()
    const reqRows = dialog.querySelectorAll('.sk-dialog__req-row')
    expect(reqRows).toHaveLength(3)
    // Per-requirement name (req-name spans are unique to each row).
    const names = Array.from(dialog.querySelectorAll('.sk-dialog__req-name')).map(
      (n) => n.textContent,
    )
    expect(names).toEqual(['jq', 'apikey', 'python'])
    // Per-requirement status chips (ready / needs setup / missing skill).
    expect(within(dialog).getByText('needs setup')).toBeInTheDocument()
    expect(within(dialog).getByText('missing skill')).toBeInTheDocument()
    expect(within(dialog).getByText('ready')).toBeInTheDocument()
    // Detail: needs_setup row shows "Missing <code>jq</code>"; declared reqs
    // show requires text ("ORACLE_KEY env", "python3").
    const jqRow = reqRows[0]!
    expect(jqRow.querySelector('.sk-dialog__req-detail')?.textContent).toContain('Missing')
    expect(jqRow.querySelector('.sk-dialog__req-detail code')?.textContent).toBe('jq')
    expect(within(dialog).getByText('ORACLE_KEY env')).toBeInTheDocument()
    expect(within(dialog).getByText('python3')).toBeInTheDocument()

    // Missing section: skill-level missing bins + env, each labelled.
    const sectionTitles = Array.from(dialog.querySelectorAll('.sk-dialog__section-title')).map(
      (t) => t.textContent,
    )
    expect(sectionTitles).toContain('Missing')
    expect(within(dialog).getByText('binary')).toBeInTheDocument()
    expect(within(dialog).getByText('env var')).toBeInTheDocument()
    const missingCodes = Array.from(dialog.querySelectorAll('.sk-dialog__missing code')).map(
      (c) => c.textContent,
    )
    expect(missingCodes).toEqual(['jq', 'ORACLE_KEY'])
  })

  // ── SK2: category badge on the registry card + detail dialog ──────────────
  // (skills.js:659-660,670,685)
  it('the registry card and detail dialog show the category badge (CAT_LABEL)', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const card = await screen.findByLabelText('Catalog skill Uniswap')
    // 'defi' → 'DeFi' label on the card.
    expect(within(card).getByText('DeFi')).toBeInTheDocument()
    // Open the detail dialog: the category chip renders there too.
    fireEvent.click(within(card).getByRole('button', { name: 'View details for Uniswap' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('DeFi')).toBeInTheDocument()
  })

  // ── SK3: Demo section heading carries the demo title + language ───────────
  // (skills.js:702-708)
  it('the registry detail Demo section shows the demo title and language labels', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const card = await screen.findByLabelText('Catalog skill Uniswap')
    fireEvent.click(within(card).getByRole('button', { name: 'View details for Uniswap' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Demo/)).toBeInTheDocument()
    // Title + language render as their own labelled spans in the heading.
    expect(within(dialog).getByText('Quote a swap')).toBeInTheDocument()
    expect(within(dialog).getByText('python')).toBeInTheDocument()
  })

  // ── #130: the Installed tab groups on provenance, not on the layer ───────
  it('groups the Installed tab into Partners / Shipped / Hub / Local', async () => {
    wireRpc({
      skills: [READY_MANAGED, NEEDS_BUNDLED, LOCAL_IN_MANAGED, BANKR_HUB_SKILL, ROBINHOOD_READY],
    })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())

    expect(screen.getAllByRole('heading').map((h) => h.textContent)).toEqual(
      expect.arrayContaining([
        'Partners',
        'Shipped with AgentOS',
        'Installed from a hub',
        'Your local skills',
      ]),
    )
    // The issue's stated criterion: Bankr and Robinhood under ONE heading,
    // even though one is a hub install and the other ships with AgentOS.
    const partners = groupNamed('Partners')
    expect(within(partners).getByLabelText('Skill bankr-swaps')).toBeInTheDocument()
    expect(within(partners).getByLabelText('Skill robinhood-rwa-addresses')).toBeInTheDocument()

    expect(
      within(groupNamed('Installed from a hub')).getByLabelText('Skill trader'),
    ).toBeInTheDocument()
    expect(
      within(groupNamed('Shipped with AgentOS')).getByLabelText('Skill weather'),
    ).toBeInTheDocument()
    // layer 'managed' with no lockfile entry is a local skill, not a hub one.
    expect(
      within(groupNamed('Your local skills')).getByLabelText('Skill handrolled'),
    ).toBeInTheDocument()
  })

  it('keeps the layer visible as a per-card detail chip', async () => {
    wireRpc({ skills: [READY_MANAGED] })
    renderPage()
    const card = await screen.findByLabelText('Skill trader')
    expect(within(card).getByText('Managed')).toBeInTheDocument()
  })

  // ── #130: Update/Remove come off the payload, not off the layer ──────────
  it('a managed-layer skill with no lockfile entry offers neither Update nor Remove', async () => {
    wireRpc({ skills: [LOCAL_IN_MANAGED] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill handrolled')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill handrolled'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('button', { name: /^Update$/i })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /^Remove$/i })).not.toBeInTheDocument()
  })

  it('a hub skill AgentOS cannot delete explains itself instead of offering a dead Remove', async () => {
    wireRpc({ skills: [STRANDED_HUB] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill stranded')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Skill stranded'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: /^Update$/i })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /^Remove$/i })).not.toBeInTheDocument()
    expect(within(dialog).getByText(/cannot remove this skill/i)).toBeInTheDocument()
  })

  // ── #130 core: installed, ready, and still not reaching the agent ────────
  it('a skill the agent is never offered says so on the card and why in the dialog', async () => {
    wireRpc({ skills: [WITHHELD_SKILL, READY_MANAGED] })
    renderPage()
    const card = await screen.findByLabelText('Skill quiet')
    // The status is untouched — this is a third state, not a failed one.
    expect(within(card).getByText('Ready')).toBeInTheDocument()
    expect(within(card).getByText('Not offered — agent cannot invoke')).toBeInTheDocument()
    // A skill that IS offered carries no such chip.
    expect(
      within(screen.getByLabelText('Skill trader')).queryByText(/Not offered/),
    ).not.toBeInTheDocument()

    fireEvent.click(card)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Agent availability')).toBeInTheDocument()
    expect(within(dialog).getByText(WITHHELD_SKILL.availability.detail)).toBeInTheDocument()
  })

  // ── #130 symptom 2: the Community list stops swapping ────────────────────
  it('a row installed while searching survives the search being cleared', async () => {
    wireRpc({
      search: (query) => (query ? [SEARCH_ONLY_ITEM] : [CATALOG_ITEM]),
      installResponse: { success: true, name: 'ledger-watch' },
    })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const input = await screen.findByLabelText('Search community skills')

    fireEvent.change(input, { target: { value: 'ledger' } })
    const card = await screen.findByLabelText('Catalog skill Ledger Watch')
    fireEvent.click(within(card).getByRole('button', { name: /^Install$/i }))
    await waitFor(() => expect(toast.success).toHaveBeenCalled())

    fireEvent.change(input, { target: { value: '' } })
    // The browse list is back…
    await screen.findByLabelText('Catalog skill Uniswap')
    // …and the row the browse itself never returned is still on it, installed.
    const stillThere = screen.getByLabelText('Catalog skill Ledger Watch')
    expect(within(stillThere).getByText('Installed')).toBeInTheDocument()
  })

  it('clearing the search does not unmount an open catalog dialog', async () => {
    wireRpc({ search: (query) => (query ? [SEARCH_ONLY_ITEM] : [CATALOG_ITEM]) })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const input = await screen.findByLabelText('Search community skills')

    fireEvent.change(input, { target: { value: 'ledger' } })
    const card = await screen.findByLabelText('Catalog skill Ledger Watch')
    fireEvent.click(within(card).getByRole('button', { name: 'View details for Ledger Watch' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '' } })
    await screen.findByLabelText('Catalog skill Uniswap')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Ledger Watch')).toBeInTheDocument()
  })

  it('uninstalling refreshes the catalog so the Installed chip is not stale', async () => {
    let removed = false
    wireRpc({
      skills: [READY_MANAGED],
      search: () => [{ ...CATALOG_ITEM, installed: !removed }],
    })
    const client = makeClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    renderPage(client)

    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const before = await screen.findByLabelText('Catalog skill Uniswap')
    expect(within(before).getByText('Installed')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Installed' }))
    fireEvent.click(await screen.findByLabelText('Skill trader'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^Remove$/i }))
    // The gateway has dropped the lockfile entry the chip is derived from.
    removed = true
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['skills.search'] }))

    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const after = await screen.findByLabelText('Catalog skill Uniswap')
    await waitFor(() =>
      expect(within(after).getByRole('button', { name: /^Install$/i })).toBeInTheDocument(),
    )
  })

  it('a failed live search shows the error instead of an empty catalog', async () => {
    wireRpc({
      search: (query) => (query ? Promise.reject(new Error('search down')) : [CATALOG_ITEM]),
    })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /^Community$/i }))
    const input = await screen.findByLabelText('Search community skills')

    fireEvent.change(input, { target: { value: 'zzz' } })
    expect(await screen.findByText(/Failed to load: Error: search down/)).toBeInTheDocument()
    expect(screen.queryByText('No skills match zzz.')).not.toBeInTheDocument()
  })

  it('sets the document title', async () => {
    wireRpc()
    renderPage()
    await waitFor(() => expect(document.title).toBe('Skills - AgentOS Control'))
  })

  it('loads and searches Capminal skills when entering the Capminal tab', async () => {
    wireRpc({
      searchResults: [
        {
          name: 'capminal',
          identifier: 'https://github.com/capminal-skills/capminal',
          provider: 'Capminal',
          source: 'capminal',
          description: 'Cap World interaction',
          category: 'crypto',
        },
      ],
    })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Skill trader')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('tab', { name: 'Capminal' }))

    const card = await screen.findByLabelText('Catalog skill capminal')
    expect(card).toBeInTheDocument()
    expect(within(card).getByText('Cap World interaction')).toBeInTheDocument()
    expect(within(card).getByText('Crypto')).toBeInTheDocument()

    fireEvent.click(within(card).getByRole('button', { name: 'View details for capminal' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Capminal')).toBeInTheDocument()
    expect(within(dialog).getByText('Crypto')).toBeInTheDocument()

    expect(mockRpc.call).toHaveBeenCalledWith('skills.search', {
      query: '',
      limit: 500,
      source: 'capminal',
    })
  })
})
