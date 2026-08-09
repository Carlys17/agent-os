export const logs = {
  documentTitle: 'Logs - AgentOS Control',
  eyebrow: 'Control · Logs',
  title: 'Logs',
  subtitle: 'Live gateway log stream — filter, follow, and export.',
  exportTitle: 'Download filtered log lines',
  export: 'Export',

  // Console header.
  consoleLandmark: 'Live log console',
  consoleEyebrow: 'Observability stream',
  consoleTitle: 'Gateway output',
  consoleCadence: 'Polling every 3s',

  // Status pills (logs.js:262-290).
  statusLandmark: 'Log status',
  statusUnavailable: 'Log status unavailable',
  statusOn: 'on',
  statusOff: 'off',
  statusFileLog: 'File log {state}',
  statusRawTurnCall: 'Raw turn-call {state}',
  statusDiagnosticsRaw: 'Diagnostics raw',
  statusDiagnosticsStandard: 'Diagnostics standard',
  statusDiagnosticsOff: 'Diagnostics off',

  // Summary tiles.
  statsLandmark: 'Log summary',
  statInView: 'In view',
  statInViewHint: 'of {total} loaded',
  statErrors: 'Errors',
  statErrorsReview: 'review needed',
  statErrorsClear: 'all clear',
  statWarnings: 'Warnings',
  statWarningsRecent: 'recent advisories',
  statWarningsNone: 'none',
  statInfoDebugLandmark: 'Info and Debug',
  statInfoDebug: 'Info / Debug',
  statInfoDebugHint: 'routine output',

  // Toolbar.
  toolbarLevels: 'Levels',
  toolbarToggleLevel: 'Toggle {level} level',
  toolbarSearchLabel: 'Filter log messages',
  toolbarSearchPlaceholder: 'Filter messages…',
  toolbarAutoFollow: 'Auto-follow',

  // Stream placeholders.
  streamLoading: 'Loading logs…',
  streamNoMatch: 'No lines match the current filter.',
  streamEmpty: 'No logs yet.',

  // Toasts.
  toastRefreshFailed: 'Log refresh failed: {message}',
  toastUnknownError: 'unknown error',
} as const
