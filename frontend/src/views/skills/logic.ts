// Pure skills-view helpers ported 1:1 from the legacy view
// (src/agentos/gateway/static/js/views/skills.js). Each function below carries
// the legacy line range it mirrors so the parity matrix stays auditable. RPC
// calls, mutations, dialogs and rendering live in SkillsPage.tsx; this module
// owns the pure derivations (filtering, layer grouping/sort, stats, category
// derivation, registry filtering, install-action state, and small utilities).

// ── Types ────────────────────────────────────────────────────────────────────

/** An installed skill row from skills.list (all fields optional). */
export interface RawSkill {
  name?: string
  description?: string
  emoji?: string
  layer?: string
  status?: string
  status_detail?: string
  eligible?: boolean
  /** Switched off by config (`skills.disabled`, or absent from `skills.enabled`).
   *  The wire `status` folds this into `needs_setup`; `skillBucket` splits it back
   *  out, because nothing about a disabled skill needs setting up. */
  disabled?: boolean
  triggers?: string[]
  homepage?: string
  file_path?: string
  missing_bins?: string[]
  missing_env?: string[]
  /** Same variables as missing_env, with whatever the manifest declared. */
  missing_env_detail?: MissingEnvDetail[]
  install?: SkillInstallOption[]
  requirements?: SkillRequirements
  /** Subject-matter grouping declared in frontmatter (`metadata.agentos.category`). */
  category?: string
  /** Allowlisted brand, or all-empty. Absent only on a pre-#130 gateway. */
  publisher?: SkillPublisher
  /** How the skill got here and what an operator may do to it. */
  acquisition?: SkillAcquisition
  /** Whether the agent is actually being offered the skill. Absent from the CLI. */
  availability?: SkillAvailability
  [key: string]: unknown
}

/**
 * The publisher block from a skill row. The server resolves it against a
 * server-side allowlist (`src/agentos/skills/publishers.py`), so `id` is the
 * ONLY trustworthy "is this a partner skill" signal — a SKILL.md cannot mint a
 * brand by writing one into its frontmatter, and the client must never infer a
 * partner from a name prefix or a homepage host.
 */
export interface SkillPublisher {
  id?: string
  name?: string
  url?: string
  logo?: string
}

/** Where a skill came from. Always present on a current gateway. */
export type SkillAcquisitionKind = 'shipped' | 'hub' | 'local'

export interface SkillAcquisition {
  kind?: SkillAcquisitionKind | string
  source_id?: string
  /**
   * The author the catalog row credited, e.g. `@igoryuzo`. Free text that
   * passed no allowlist — unlike `publisher`, which the server resolves. Render
   * it as attribution only: never with a logo, never as a trust signal. Empty
   * only when it would repeat the resolved `publisher`, so a partner skill is
   * credited once rather than twice; a partner-distributed skill written by
   * someone else keeps the handle.
   */
  author?: string
  identifier?: string
  version?: string
  installed_at?: string
  source_trust?: string
  scan_verdict?: string
  /** Gates the Remove button. */
  removable?: boolean
  /** Gates the Update button. */
  updatable?: boolean
}

/** Why the agent is not being offered an installed, eligible skill. */
export type SkillAvailabilityReason =
  | ''
  | 'model_invocation_disabled'
  | 'ineligible'
  | 'tool_gate'
  | 'fallback_superseded'
  | 'not_retrieved'
  | 'prompt_budget'

export interface SkillAvailability {
  offered?: boolean
  reason?: SkillAvailabilityReason | string
  /** Tooltip prose; never carries a filesystem path. */
  detail?: string
}

export interface MissingEnvDetail {
  name: string
  description?: string
  url?: string
  secret?: boolean | null
  required?: boolean
}

export interface SkillInstallOption {
  id?: string
  kind?: string
  label?: string
  bins?: string[]
}

export interface SkillRequirements {
  items?: SkillRequirementItem[]
}

export interface SkillRequirementItem {
  name?: string
  status?: string
  missing_bins?: string[]
  missing_env?: string[]
  requires_bins?: string[]
  requires_any_bins?: string[]
  requires_env?: string[]
}

/** A registry/catalog row from skills.search (bankr / community). */
export interface RegistryItem {
  name?: string
  identifier?: string
  provider?: string
  source?: string
  description?: string
  category?: string
  logo?: string
  emoji?: string
  homepage?: string
  trust_level?: string
  installed?: boolean
  setup?: string[]
  demo?: { code?: string; language?: string; title?: string }
  [key: string]: unknown
}

/** The status-filter keys the metric pills toggle (skills.js:352-366). */
export type StatusFilter = 'all' | 'ready' | 'needs-setup' | 'disabled'

/**
 * The bucket a card is shown in — a different axis from the wire `status`.
 *
 * Two regroupings happen here, both display decisions:
 *
 * 1. `not_declared` joins `ready`. The wire keeps them apart to record whether
 *    AgentOS verified anything, but for someone reading the list they mean the
 *    same thing — the skill runs. Splitting them put working skills in a
 *    separate bucket that read as a defect, and no action ever followed.
 *    `status_detail` still distinguishes "3/3 satisfied" from "no dependencies
 *    declared" in the tooltip, which is where that nuance belongs.
 * 2. `disabled` leaves `needs_setup`. The gateway folds it in because both mean
 *    `eligible: false`, but they are opposite problems: a disabled skill needs
 *    nothing installed, and listing it under "Needs setup" both inflates that
 *    count and offers a fix that does not exist. `disabled` is already on the
 *    wire (`rpc_skills.py`), so the split costs no protocol change.
 */
export type SkillBucket = 'ready' | 'needs-setup' | 'disabled'

export function skillBucket(skill: RawSkill): SkillBucket {
  if (skill.disabled) return 'disabled'
  // Via `skillStatus`, not the raw field: a payload without `status` (an older
  // gateway, a hand-built row) used to count in no pill at all and vanish from
  // every filter except All.
  //
  // Only `needs_setup` is a problem. Anything else — `ready`, `not_declared`,
  // or a value a newer gateway invented — is a skill that runs. Amber is a call
  // to action, and inventing one for a status this build cannot read would send
  // an operator looking for a dependency that was never missing.
  return skillStatus(skill) === 'needs_setup' ? 'needs-setup' : 'ready'
}

// ── Constants (skills.js:36-58) ──────────────────────────────────────────────

// `layer` is a location, not a provenance: it says which directory a SKILL.md
// was loaded from. It is still shown as a per-card detail chip, but it no
// longer groups the Installed tab (see SKILL_GROUP_ORDER below) — grouping on
// it split the same partner's skills across two headings.

export const LAYER_LABEL: Record<string, string> = {
  workspace: 'Workspace',
  bundled: 'Bundled',
  managed: 'Managed',
  personal: 'Personal',
  project: 'Project',
  extra: 'Extra',
}

export const LAYER_HELP: Record<string, string> = {
  workspace: 'Workspace skills are local to the active workspace.',
  bundled: 'Bundled skills ship with AgentOS.',
  managed: 'Managed skills are locally installed into AgentOS state.',
  personal: 'Personal skills are local user installs, not bundled.',
  project: 'Project skills are local to the current project.',
  extra: 'Extra skills come from configured local directories.',
}

export const CAT_LABEL: Record<string, string> = {
  all: 'All',
  trading: 'Trading',
  defi: 'DeFi',
  wallet: 'Wallets',
  markets: 'Markets',
  social: 'Social',
  data: 'Data',
  nft: 'NFT',
  dev: 'Dev tools',
  infra: 'Infra',
  crypto: 'Crypto',
  other: 'Other',
}

/** skills.js:210,220 — the registry-search debounce interval (ms). */
export const REGISTRY_SEARCH_DEBOUNCE_MS = 250

// ── Layer label/help (skills.js:1070-1076) ───────────────────────────────────

export function layerLabel(layer?: string): string {
  return (layer && LAYER_LABEL[layer]) || layer || 'Unknown'
}

export function layerHelp(layer?: string): string {
  return (layer && LAYER_HELP[layer]) || 'Configured local skill directory.'
}

// ── Installed stats (skills.js:342-367) ──────────────────────────────────────

export interface SkillStats {
  total: number
  ready: number
  needs: number
  disabled: number
}

export function skillStats(skills: RawSkill[]): SkillStats {
  const bucket = (want: SkillBucket) => skills.filter((s) => skillBucket(s) === want).length
  return {
    total: skills.length,
    ready: bucket('ready'),
    needs: bucket('needs-setup'),
    disabled: bucket('disabled'),
  }
}

// ── Installed filter (skills.js:374-388) ─────────────────────────────────────

/**
 * skills.js:374-388 — filter installed skills by the free-text filter (name /
 * description / triggers, case-insensitive) then the active status pill.
 * `filterText` is expected already-lowercased (legacy keeps `_filterText`
 * lowercased); we lowercase again defensively so the helper is order-safe.
 */
export function filterSkills(
  skills: RawSkill[],
  filterText: string,
  statusFilter: StatusFilter,
): RawSkill[] {
  const q = (filterText || '').toLowerCase()
  let out = skills
  if (q) {
    out = out.filter(
      (s) =>
        (s.name || '').toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.triggers || []).some((t) => t.toLowerCase().includes(q)),
    )
  }
  if (statusFilter !== 'all') out = out.filter((s) => skillBucket(s) === statusFilter)
  return out
}

/** skills.js:391-399 — the empty-state message for the installed list. */
export function installedEmptyMessage(filterText: string, statusFilter: StatusFilter): string {
  if (filterText) return `No skills match ${filterText}.`
  if (statusFilter === 'ready') return 'No skills are ready. Install dependencies to enable them.'
  if (statusFilter === 'needs-setup') return 'No skills currently need setup.'
  if (statusFilter === 'disabled') return 'No skills are switched off.'
  return 'No skills installed.'
}

// ── Provenance grouping + ready-first sort (skills.js:407-442) ────────────────

/**
 * skills.js:407-411 — sort rank, usable first.
 *
 * ready(0) < disabled(1) < needs_setup(2). Disabled sorts above needs-setup
 * because nothing is broken about it: it is one config line away from working,
 * where a needs-setup skill is waiting on the environment.
 */
export function skillRank(s: RawSkill): number {
  const bucket = skillBucket(s)
  if (bucket === 'ready') return 0
  if (bucket === 'disabled') return 1
  return 2
}

/** The Installed tab's headings, in the order they render. */
export type SkillGroupKey = 'partners' | 'crypto' | 'shipped' | 'hub' | 'local'

export const SKILL_GROUP_ORDER: readonly SkillGroupKey[] = [
  'partners',
  'crypto',
  'shipped',
  'hub',
  'local',
] as const

export const SKILL_GROUP_LABEL: Record<SkillGroupKey, string> = {
  partners: 'Partner Skills',
  crypto: 'AgentOS Crypto Skills',
  shipped: 'AgentOS Normal Skills',
  hub: 'Installed from a hub',
  local: 'Your local skills',
}

export const SKILL_GROUP_HELP: Record<SkillGroupKey, string> = {
  partners: 'Skills published by an AgentOS partner.',
  crypto: 'On-chain and wallet skills that ship with AgentOS.',
  shipped: 'Skills that ship with AgentOS.',
  hub: 'Skills you installed from a skill hub.',
  local: 'Skills you added yourself, from a local skill directory.',
}

/**
 * Whether a skill declares itself as on-chain / wallet subject matter.
 *
 * Reads the manifest's `category`, never the name: inferring a topic from a
 * string in the name is the same mistake `skillPublisherId` exists to avoid, and
 * it would mean editing and rebuilding the frontend for every new crypto skill.
 */
export function isCryptoSkill(skill: RawSkill): boolean {
  return (skill.category ?? '').trim().toLowerCase() === 'crypto'
}

/**
 * The single group a skill belongs to. Partners wins over provenance so a
 * partner's skills sit under one heading whether they shipped with AgentOS or
 * were installed from that partner's hub — grouping on `layer` split them.
 *
 * A row from a pre-#130 gateway carries no `acquisition`; fall back to the
 * location layer so an older gateway still renders something sane rather than
 * filing every skill under "Shipped with AgentOS".
 */
export function skillGroupKey(skill: RawSkill): SkillGroupKey {
  if (isPartnerSkill(skill)) return 'partners'
  const kind = skill.acquisition?.kind
  // Crypto is a split of `shipped`, not a fifth provenance. Gating it on shipped
  // is deliberate: a directory a user dropped into their skills dir must not be
  // able to claim a heading that carries the AgentOS name just by writing
  // `category: crypto` — the same reasoning as SELF_DECLARING_LAYERS for publishers.
  if (kind === 'shipped' || (!kind && skill.layer === 'bundled')) {
    return isCryptoSkill(skill) ? 'crypto' : 'shipped'
  }
  if (kind === 'hub' || kind === 'local') return kind
  if (skill.layer === 'managed') return 'hub'
  return 'local'
}

/**
 * Whether an operator may update / remove a skill.
 *
 * What an operator may do comes off `acquisition`, not off the layer: a hub
 * install stays removable when `skills.managed_dir` moves, and a hand-copied
 * directory inside the managed dir was never removable in the first place.
 *
 * A row from a pre-#130 gateway carries no `acquisition` at all. Reading the
 * flags directly would then be `undefined === true` → `false`, silently hiding
 * both buttons rather than degrading — so fall back to the layer test these
 * buttons used before, exactly as `skillGroupKey` does.
 */
export function skillCanUpdate(skill: RawSkill): boolean {
  if (skill.acquisition) return skill.acquisition.updatable === true
  return skill.layer === 'managed'
}

export function skillCanRemove(skill: RawSkill): boolean {
  if (skill.acquisition) return skill.acquisition.removable === true
  return skill.layer === 'managed'
}

export interface SkillGroup {
  key: SkillGroupKey
  label: string
  help: string
  skills: RawSkill[]
}

/** Sort a bucket ready-first (skills.js:407-411) then name-asc. */
function sortByReady(list: RawSkill[]): RawSkill[] {
  return list.sort((a, b) => {
    const ra = skillRank(a)
    const rb = skillRank(b)
    if (ra !== rb) return ra - rb
    return (a.name || '').localeCompare(b.name || '')
  })
}

/**
 * skills.js:413-442, regrouped — bucket the filtered skills by provenance,
 * sort each bucket ready-first then name-asc, and emit groups in
 * SKILL_GROUP_ORDER (skipping empties). A skill lands in exactly one group.
 */
export function groupSkills(skills: RawSkill[]): SkillGroup[] {
  const groups: Partial<Record<SkillGroupKey, RawSkill[]>> = {}
  skills.forEach((s) => {
    const k = skillGroupKey(s)
    ;(groups[k] = groups[k] || []).push(s)
  })
  const out: SkillGroup[] = []
  SKILL_GROUP_ORDER.forEach((key) => {
    const list = groups[key]
    if (!list || list.length === 0) return
    out.push({
      key,
      label: SKILL_GROUP_LABEL[key],
      help: SKILL_GROUP_HELP[key],
      skills: sortByReady(list),
    })
  })
  return out
}

// ── Card status → tone/label (skills.js:447-465, 779-789) ─────────────────────

/** The card status dot class: ready / needs / off. */
export type SkillDot = 'is-ready' | 'is-needs' | 'is-off'

/** skills.js:448 — resolve a skill's effective status (falls back to eligible). */
export function skillStatus(skill: RawSkill): string {
  return skill.status || (skill.eligible ? 'ready' : 'needs_setup')
}

/** skills.js:449-452 — the status-dot class for a card. */
export function skillDotClass(skill: RawSkill): SkillDot {
  const bucket = skillBucket(skill)
  if (bucket === 'ready') return 'is-ready'
  // Amber says "act on this". A switched-off skill needs no action, so it goes
  // grey rather than joining the warnings an operator is meant to work through.
  if (bucket === 'disabled') return 'is-off'
  return 'is-needs'
}

/** The label under the dot, per bucket. */
export const SKILL_BUCKET_LABEL: Record<SkillBucket, string> = {
  ready: 'Ready',
  'needs-setup': 'Setup required',
  disabled: 'Disabled',
}

/** skills.js:454 — the dot tooltip. */
export function skillDotTitle(skill: RawSkill): string {
  if (skill.disabled) return skill.status_detail || 'Disabled in config'
  return skill.status_detail || (skill.eligible ? 'Ready' : 'Needs setup')
}

// ── Availability: installed and eligible, but is it offered? ──────────────────

/**
 * The card's third state. `status` answers "can this skill run"; availability
 * answers "is the agent even being told about it" — a skill can be perfectly
 * ready and still never reach the model (model invocation disabled, a missing
 * tool, the prompt budget). 'unknown' is what an absent block means: the CLI
 * never computes availability, and treating that as not-offered would be a
 * fabricated verdict.
 */
export type SkillAvailabilityTone = 'offered' | 'not-offered' | 'unknown'

export function skillAvailabilityTone(skill: RawSkill): SkillAvailabilityTone {
  const offered = skill.availability?.offered
  if (typeof offered !== 'boolean') return 'unknown'
  return offered ? 'offered' : 'not-offered'
}

/** Short labels per withheld reason, for the card chip. */
export const AVAILABILITY_REASON_LABEL: Record<string, string> = {
  model_invocation_disabled: 'Not offered — agent cannot invoke',
  ineligible: 'Not offered — needs setup',
  tool_gate: 'Not offered — missing tools',
  fallback_superseded: 'Not offered — superseded',
  not_retrieved: 'Not offered — not retrieved',
  prompt_budget: 'Not offered — prompt too long',
}

/** The chip label; '' when availability was not computed (nothing to show). */
export function skillAvailabilityLabel(skill: RawSkill): string {
  const tone = skillAvailabilityTone(skill)
  if (tone === 'unknown') return ''
  if (tone === 'offered') return 'Offered to the agent'
  const reason = String(skill.availability?.reason || '')
  return AVAILABILITY_REASON_LABEL[reason] || 'Not offered to the agent'
}

/** The chip tooltip: the server's prose when it wrote any, else the label. */
export function skillAvailabilityTitle(skill: RawSkill): string {
  return skill.availability?.detail || skillAvailabilityLabel(skill)
}

// ── Partner (publisher) selection ─────────────────────────────────────────────

/**
 * The skill's brand slug, or '' for an ordinary skill.
 *
 * This is the ONLY partner signal the client honours. The old heuristic read
 * the skill's own name and homepage and leaned on `layer === 'bundled'` to stop
 * a community skill wearing the banner; that guard now lives server-side, where
 * `publisher.id` is resolved against an allowlist before it reaches the wire.
 * Re-deriving a brand from a name here would reopen exactly the hole the
 * allowlist closes, so nothing below looks at `name` or `homepage`.
 */
export function skillPublisherId(skill: RawSkill): string {
  return String(skill.publisher?.id || '')
    .trim()
    .toLowerCase()
}

/** True when the row carries any allowlisted brand. */
export function isPartnerSkill(skill: RawSkill): boolean {
  return skillPublisherId(skill) !== ''
}

/** The installed skills of one partner, name-sorted (skills.js:484-486). */
export function skillsByPublisher(skills: RawSkill[], publisherId: string): RawSkill[] {
  const want = (publisherId || '').trim().toLowerCase()
  if (!want) return []
  return skills
    .filter((s) => skillPublisherId(s) === want)
    .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
}

/** The empty-state prose for a partner tab, e.g. `partnerEmptyMessage('Robinhood', …)`. */
export function partnerEmptyMessage(
  brand: string,
  filterText: string,
  statusFilter: StatusFilter,
): string {
  const query = (filterText || '').trim()
  if (query) return `No ${brand} skills match ${query}.`
  if (statusFilter === 'ready') return `No ${brand} skills are ready.`
  if (statusFilter === 'needs-setup') return `No ${brand} skills currently need setup.`
  if (statusFilter === 'disabled') return `No ${brand} skills are switched off.`
  return `${brand} skills are on the way. No ${brand} skills are installed yet.`
}

// ── Registry (community / bankr) derivations ──────────────────────────────────

/**
 * skills.js:503-505 — when the dedicated Bankr tab is showing, Community
 * excludes source==='bankr' rows; otherwise Bankr falls through into Community.
 */
export function communityFilter(
  results: RegistryItem[],
  showBankr: boolean,
  showCapminal: boolean,
): RegistryItem[] {
  let out = results
  if (showBankr) {
    out = out.filter((r) => r.source !== 'bankr')
  }
  if (showCapminal) {
    out = out.filter((r) => r.source !== 'capminal')
  }
  return out
}

/** skills.js:560-564 — category → count map over a registry list. */
export function categoriesFor(list: RegistryItem[]): Record<string, number> {
  const counts: Record<string, number> = {}
  list.forEach((r) => {
    const c = r.category || 'other'
    counts[c] = (counts[c] || 0) + 1
  })
  return counts
}

export interface CategoryChip {
  cat: string
  label: string
  count: number
  active: boolean
}

/**
 * skills.js:567-587 — chips derive from the FULL snapshot only (never change on
 * keystrokes). No chips when there are no items, or only the 'other' category.
 * 'all' leads, then categories sorted by count desc.
 */
export function categoryChips(snapshot: RegistryItem[], activeCat: string): CategoryChip[] {
  const counts = categoriesFor(snapshot)
  const keys = Object.keys(counts)
  const hasCats = keys.some((c) => c && c !== 'other') || keys.length > 1
  if (!hasCats || !snapshot.length) return []
  const cats = ['all', ...keys.sort((a, b) => (counts[b] ?? 0) - (counts[a] ?? 0))]
  return cats.map((c) => ({
    cat: c,
    label: CAT_LABEL[c] || c,
    count: c === 'all' ? snapshot.length : (counts[c] ?? 0),
    active: activeCat === c,
  }))
}

export interface RegistryFilterOptions {
  /**
   * True when `items` IS the server's answer to `query`. The text pass is then
   * skipped entirely and only the category chip narrows the list.
   *
   * The server matches over name, provider, category, description and **tags**
   * (`skills/hub/bankr.py:_matches`), and tags are not on the wire — so no
   * client matcher can ever reproduce it, and re-filtering a server result can
   * only throw away legitimate hits. The text pass survives for the debounce
   * window, where it narrows a stale list optimistically while the request is
   * still out; dropping a row there is harmless because the answer replaces it.
   */
  serverFiltered?: boolean
}

/**
 * skills.js:610-620 — apply the category filter then the case-insensitive text
 * filter to a registry list. `query` is trimmed + lowercased here (legacy
 * trims/lowercases inline).
 *
 * The text pass also matches `category`, which the server matches and the
 * original client matcher did not; that is as close to the server as the
 * payload allows. Pass `{ serverFiltered: true }` once the rows on screen are
 * the server's own answer.
 */
export function filterRegistry(
  items: RegistryItem[],
  category: string,
  query: string,
  options: RegistryFilterOptions = {},
): RegistryItem[] {
  let out = items
  const cat = category || 'all'
  if (cat !== 'all') out = out.filter((r) => (r.category || 'other') === cat)
  if (options.serverFiltered) return out
  const q = (query || '').trim().toLowerCase()
  if (q) {
    out = out.filter(
      (r) =>
        (r.name || '').toLowerCase().includes(q) ||
        (r.provider || '').toLowerCase().includes(q) ||
        (r.description || '').toLowerCase().includes(q) ||
        (r.category || '').toLowerCase().includes(q),
    )
  }
  return out
}

/** skills.js:622-626 — the empty message for a registry group + query. */
export function registryEmptyMessage(
  group: 'bankr' | 'capminal' | 'community',
  query: string,
): string {
  const q = (query || '').trim()
  if (q) return `No skills match ${q}.`
  if (group === 'bankr') return 'No Bankr skills available right now.'
  if (group === 'capminal') return 'No Capminal skills available right now.'
  return 'No community skills available right now.'
}

/** skills.js:662,715,283 — the stable identifier key for a registry row. */
export function registryKey(r: RegistryItem): string {
  return r.identifier || r.name || ''
}

/**
 * Union two registry lists by `registryKey`, `base` winning on a collision.
 *
 * The gateway now synthesizes a row for an install no catalog lists, so a
 * refetch alone is enough to make it appear — but only once the refetch lands.
 * Merging the just-installed row in locally shows it on the same tick, and the
 * server's richer row replaces it on the next fetch because `base` (the query
 * result) wins. `extra` rows are appended for the same reason the server
 * appends its synthesized ones: they carry no relevance score and must not push
 * ranked catalog rows off the top of the grid.
 *
 * A row with no identifier and no name cannot be keyed, deduped or installed,
 * so it is dropped rather than appended blind.
 */
export function mergeRegistryRows(base: RegistryItem[], extra: RegistryItem[]): RegistryItem[] {
  const seen = new Set(base.map(registryKey).filter(Boolean))
  const out = [...base]
  extra.forEach((r) => {
    const key = registryKey(r)
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push(r)
  })
  return out
}

// ── Install-action state (skills.js:633-641) ──────────────────────────────────

export type InstallActionKind = 'installed' | 'force' | 'install'

/**
 * skills.js:633-641 — the install button's state for a registry row: already
 * installed → a static badge; force-armed (post security-block) → a danger
 * force-install; otherwise a normal install.
 */
export function installAction(r: RegistryItem, forceArmed: Set<string>): InstallActionKind {
  if (r.installed) return 'installed'
  const key = registryKey(r)
  if (forceArmed.has(key)) return 'force'
  return 'install'
}

/** skills.js:254,640 — the source to install from (default 'clawhub'). */
export function installSource(r: RegistryItem): string {
  return r.source || 'clawhub'
}

// ── deps.install still-missing (skills.js:894-896) ────────────────────────────

export interface DepsInstallResult {
  success?: boolean
  message?: string
  missing_still?: { bins?: string[]; env?: string[] }
}

/** skills.js:894-896 — count of deps still missing after a deps.install. */
export function stillMissingCount(res: DepsInstallResult): number {
  const still = res.missing_still || {}
  return (still.bins || []).length + (still.env || []).length
}

// ── update result unwrap (skills.js:1000-1007) ────────────────────────────────

export interface UpdateResult {
  results?: Array<{ success?: boolean; message?: string }>
  message?: string
}

/** skills.js:1000 — skills.update returns a results[] array; take the first. */
export function firstUpdateResult(res: UpdateResult): { success?: boolean; message?: string } {
  return (res.results || [])[0] || {}
}

// ── Small utilities ──────────────────────────────────────────────────────────

/** skills.js:1019-1023 — provider/name initials for a logo fallback. */
export function initials(text?: string): string {
  const words = (text || '').trim().split(/\s+/).filter(Boolean)
  const first = words[0]
  if (!first) return '?'
  const second = words[1]
  return ((first[0] ?? '') + (second ? (second[0] ?? '') : '')).toUpperCase()
}

/** skills.js:1030-1033 — allow only http(s) URLs from remote catalogs. */
export function safeUrl(url?: string): string {
  const u = String(url || '').trim()
  return /^https?:\/\//i.test(u) ? u : ''
}

/**
 * skills.js:911-924 — flip `installed` on rows matching by identifier or name
 * across a cached registry list. Returns a NEW array (React-friendly) rather
 * than mutating, but preserves the legacy match semantics.
 *
 * Kept, not deleted: this is the optimistic half of the install/uninstall
 * round trip. It is applied from `installMutation.onSuccess` /
 * `uninstallMutation.onSuccess` in SkillsPage.tsx over the cached
 * `['skills.search', …]` data before the invalidation refetch lands, so the
 * Installed chip flips on the same tick instead of after a network round trip.
 * Both paths then invalidate `['skills.search']` so the server's own answer
 * replaces the optimistic one.
 */
export function markInstalled(
  list: RegistryItem[],
  identifier: string,
  name: string,
  installed: boolean,
): RegistryItem[] {
  return list.map((r) => {
    const key = registryKey(r)
    if ((identifier && key === identifier) || (name && r.name === name)) {
      return { ...r, installed }
    }
    return r
  })
}
