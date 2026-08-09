import { defineNamespace } from '../registry'

export const channels = defineNamespace('channels', {
  documentTitle: 'Channels - AgentOS Control',
  eyebrow: 'Control · Channels',
  title: 'Channels',
  subtitle: 'Add messaging adapters, monitor runtime health, and pair Telegram connections.',
  refresh: 'Refresh',
  refreshBusy: 'Refreshing…',
  addChannel: 'Add channel',

  // Command strip + stat tiles.
  operationsLandmark: 'Channel operations',
  meshEyebrow: 'Integration mesh',
  meshTitle: 'Channel posture',
  cadence: 'Live · refreshes every 5s',
  statsLandmark: 'Channels summary',
  statTotal: 'Total channels',
  statTotalHint_one: '{count} type configured',
  statTotalHint_other: '{count} types configured',
  statConnected: 'Connected',
  statConnectedLive: 'live now',
  statConnectedUnhealthy: '{count} unhealthy',
  statConnectedIdle: 'all idle',
  statInactive: 'Inactive',
  statInactiveAttention: '{count} need attention',
  statRestarts: 'Restart attempts',
  statRestartsHint: 'since gateway start',
  statPairing: 'Pairing requests',
  statPairingWaiting: 'Telegram connections waiting',
  statPairingIdle: 'nothing waiting',

  // Channel list.
  listTitle: 'Configured channels',
  listDescription: 'Runtime adapters, connection health, and Telegram pairing in one place.',
  listCount_one: '{count} channel',
  listCount_other: '{count} channels',
  emptyTitle: 'No configured channels.',
  emptyMsg:
    'Connect Telegram, Slack, Discord, or another adapter here. AgentOS validates the configuration before saving and keeps credentials write-only.',
  emptyAction: 'Add your first channel',

  // Channel card.
  cardTypeUnknown: 'unknown',
  cardConfigure: 'Configure',
  cardAdvanced: 'Advanced config',
  cardLoading: 'Loading…',
  cardConnected: 'Connected',
  cardRestartAttempts: 'Restart attempts',
  cardAdapterConfig: 'Adapter config',

  // Telegram pairing panel.
  accessEyebrow: 'Telegram connections',
  accessTitle: 'Pairing',
  accessLocked: 'Pairing is locked for one hour after repeated invalid codes.',
  accessNoteLead: 'Direct messages always require pairing.',
  // Two whole sentences rather than a sentence plus a padded ' and a bot
  // mention' fragment: catalog.test.ts rejects padded values, and a translator
  // cannot place a dangling clause correctly anyway.
  accessGroupsEnabled: '{count} configured group(s) also require a paired sender.',
  accessGroupsEnabledMention:
    '{count} configured group(s) also require a paired sender and a bot mention.',
  accessGroupsDisabled: 'Group messaging is disabled.',
  accessPendingTitle: 'Pending pairing',
  accessPairedTitle: 'Paired',
  accessNoPending: 'No Telegram connections are waiting to pair.',
  accessNoPaired: 'No paired Telegram connections yet.',
  accessPair: 'Pair',
  accessDeny: 'Deny',
  accessDisconnect: 'Disconnect',

  // Setup dialog chrome.
  panelTitleEdit: 'Configure {name}',
  panelTitleAdd: 'Add a channel',
  setupTryAgain: 'Try again',
  setupOpenAdvanced: 'Open Advanced config',
  setupGuide: 'Setup guide',
  feedbackWriteBlocked: 'Configuration changed on disk. Reload the gateway state before saving.',
  feedbackConflict: 'Settings changed elsewhere. Your channel draft is still preserved.',
  feedbackUseLatest: 'Use latest version',
  feedbackWriteOnly: 'Credentials are write-only and never shown again.',
  discardKeepEditing: 'Keep editing',
  discardConfirm: 'Discard draft',
  setupEditTitle: 'Channel configuration',
  setupNewTitle: 'New integration',
  setupEditSubtitle: 'Update this adapter without exposing its saved credentials.',
  setupNewSubtitle: 'Choose an adapter, add its credentials, then validate and save it.',
  setupClose: 'Close channel setup',
  setupProgress: 'Channel setup progress',
  setupLoading: 'Loading channel options…',
  setupLoadingHint: 'Reading the current configuration and adapter catalog.',
  setupLoadFailed: 'Channel setup could not be loaded.',
  setupNoAdapters: 'No channel adapters are available.',
  setupNoAdaptersHint: 'Check the gateway catalog, then refresh this page.',
  setupNeedsAdvancedTitle: 'This adapter needs Advanced config.',
  setupNeedsAdvancedBody:
    '{type} is running, but it is not available in the guided channel catalog.',

  // Setup dialog steps.
  stepOne: 'Step 1',
  stepOneTitle: 'Choose an adapter',
  stepTypeLocked: 'Type locked while editing',
  stepAdapterLandmark: 'Channel adapter',
  adapterTransportFallback: 'messaging adapter',
  stepTwo: 'Step 2',
  stepTwoTitle: '{adapter} details',
  beforeYouStart: 'Before you start',
  advancedOptions: 'Advanced options',
  toggleOn: 'On',
  toggleOff: 'Off',
  saveValidating: 'Validating…',
  saveUpdate: 'Validate & update',
  saveAdd: 'Validate & add',

  // Discard confirmation.
  discardTitle: 'Discard this channel draft?',
  discardBodyNavigating: 'Leaving this page will clear unsaved credentials and field changes.',
  discardBody: 'Your unsaved credentials and field changes will be cleared.',
  unsavedBlocker: 'Channel setup has unsaved changes.',

  // Toasts.
  toastLoadFailed: 'Failed to load channels: {message}',
  toastSavedRestart: 'Channel saved. Restart AgentOS to activate it.',
  toastSaved: 'Channel saved.',
  toastConflict: 'Channel draft needs a fresh configuration.',
  toastPaired: 'Telegram connection paired.',
  toastPairingDenied: 'Telegram pairing denied.',
  toastResolveFailed: 'Failed to resolve pairing request: {message}',
  toastDisconnected: 'Telegram connection disconnected.',
  toastRevokeFailed: 'Failed to disconnect Telegram: {message}',

  // Derived copy (logic.ts).
  nameUnknown: 'Unknown',
  inactiveNone: 'no inactive channels',
  inactiveDisabled: '{count} disabled',
  inactiveIdle: 'configured but idle',
  hintDisabled:
    'Disabled in config — gateway restart required after re-enabling. Run `agentos onboard configure channels` to change.',
  hintDead: 'Adapter is dead. Inspect gateway logs, then `agentos channels restart {name}`.',
  hintRunning: 'Adapter is live in the current gateway process.',
  hintRestarting: 'Adapter is restarting after dispatch errors.',
  hintExhausted: 'Adapter exhausted its retry budget. Try `agentos channels restart {name}`.',
  hintConfigured:
    'Configured on disk but not active in this gateway process — restart the gateway to load it.',
  senderFallback: 'Telegram user {id}',
  senderUnknownId: 'unknown',
  senderMetaId: 'ID {id}',
  senderMetaExpires: 'expires {time}',
} as const)
