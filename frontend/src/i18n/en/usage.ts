import { defineNamespace } from '../registry'

export const usage = defineNamespace('usage', {
  documentTitle: 'Usage - AgentOS Control',
  eyebrow: 'Control · Analytics',
  title: 'Usage',
  subtitle: 'Tokens, cost, and per-model spend across every session.',
  exportTitle: 'Download CSV',
  export: 'Export CSV',
  refresh: 'Refresh',
  refreshBusy: 'Refreshing',

  // Error state.
  errorTitle: 'Usage data is unavailable',
  errorFallback: 'The gateway did not return usage data.',
  toastLoadFailed: 'Failed to load usage: {message}',

  // Range picker.
  rangeAll: 'All',
  range7: '7d',
  range14: '14d',
  range30: '30d',
  rangeLabelAll: 'All recorded activity',
  rangeLabelDays: 'Last {days} days',
  hiddenSessions_one: '{count} undated legacy session hidden',
  hiddenSessions_other: '{count} undated legacy sessions hidden',

  // Overview.
  metricSpend: 'Period spend',
  metricTokens: 'Token volume',
  summaryLandmark: 'Usage summary',
  billingWindow: 'Billing window',
  dateRange: 'Date range',
  totalCost: 'Total cost',
  noCostSource: 'No cost source yet',
  totalTokens: 'Total tokens',
  dtInput: 'Input',
  dtOutput: 'Output',
  dtCacheRead: 'Cache read',
  dtCacheWrite: 'Cache write',
  sessionsLandmark: 'Sessions',
  dtSessions: 'Sessions',
  hintInWindow: 'in this window',
  averageLandmark: 'Avg cost / session',
  dtAverage: 'Average / session',
  hintRunningAverage: 'running average',

  // Chart.
  chartTitle: 'Session footprint',
  chartSubtitle: 'Compare the highest-consumption sessions in the selected window.',
  chartMetric: 'Chart metric',
  segTokens: 'Tokens',
  segCost: 'Cost',
  chartCaptionCost: 'Top sessions by cost',
  chartCaptionTokens: 'Top sessions by total tokens',
  chartCaptionWithPool: '{caption} · showing {shown} of {pool}',
  legendInput: 'Input',
  legendOutput: 'Output',
  chartEmptyTitle: 'No data in the selected window.',
  chartEmptyMsg: 'Choose a wider billing window or run a new session.',
  barTitle: 'Open {key}',

  // Model allocation.
  modelsTitle: 'Model allocation',
  modelsSubtitle: 'Token volume, session reach, and cost contribution by model.',
  modelCount_one: '{count} model',
  modelCount_other: '{count} models',
  modelsEmpty: 'No model usage yet.',
  modelsLandmark: 'By model breakdown',
  shareTitle: 'Share of total cost',
  ofSpend: 'of spend',
  dtTokens: 'Tokens',
  dtInputOutput: 'Input / output',
  dtCost: 'Cost',

  // Sessions table.
  tableTitle: 'Sessions',
  tableSubtitle: 'Auditable usage records with provider billing provenance.',
  sessionCount_one: '{count} session',
  sessionCount_other: '{count} sessions',
  colSession: 'Session',
  colModified: 'Modified',
  colInput: 'Input',
  colOutput: 'Output',
  colCacheRead: 'Cache R',
  colCacheWrite: 'Cache W',
  colCost: 'Cost',
  colSource: 'Source',
  colModel: 'Model',
  tableEmptyTitle: 'No usage data yet',
  tableEmptyMsg: 'Run a session and token spend will appear here automatically.',
  openChatFor: 'Open chat for {key}',
  loadingLabel: 'Loading usage data',

  // Inline per-model expansion.
  expandEyebrow: 'Model breakdown',
  expandModels_one: '{count} model',
  expandModels_other: '{count} models',
  expandTotal: '{tokens} tokens · {cost}',
  expandProrated: 'Per-model split is estimated; total is the actual billed amount.',

  // Cost-source badges (logic.ts).
  sourceEphemeral: 'Ephemeral',
  sourceActual: 'Actual',
  sourceEstimated: 'Estimated',
  sourceMixed: 'Mixed',
  sourceUnpriced: 'Unpriced',
  sourceNone: 'None',
  tipEphemeral: 'Ephemeral session — cost not yet persisted',
  tipActual: 'Actual — cost billed by the provider',
  tipProrated: 'Total is real billed; per-model split is estimated.',
  tipEstimated: 'Estimated — derived locally from token counts',
  tipMixed: 'Mixed — partial billing data, rest estimated',
  tipUnpriced: 'Unpriced — no pricing table entry for this model',
  tipNone: 'No cost recorded',

  // Composition hint. Stored lowercase rather than lowercasing the badge label
  // at runtime — `toLowerCase()` on a translated noun is wrong in languages
  // that capitalise them.
  compositionActual: 'actual',
  compositionEstimated: 'estimated',
  compositionMixed: 'mixed',
  compositionUnpriced: 'unpriced',
  compositionEphemeral: 'ephemeral',
  compositionEntry: '{label} {count}',

  // Relative timestamps (logic.ts).
  relJustNow: 'just now',
  relMinutes: '{count}m ago',
  relHours: '{count}h ago',
  relDays: '{count}d ago',
} as const)
