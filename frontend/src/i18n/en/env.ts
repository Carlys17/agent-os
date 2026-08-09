export const env = {
  documentTitle: 'Environment - AgentOS Control',
  eyebrow: 'Configuration',
  title: 'Environment',
  subtitle:
    'Credentials and settings the gateway, its providers, and your skills read from the environment.',
  refresh: 'Refresh',
  addVariable: 'Add variable',

  // Category labels.
  categoryProvider: 'LLM providers',
  categorySearch: 'Search',
  categoryImage: 'Image generation',
  categoryAudio: 'Audio',
  categoryMemory: 'Memory embedding',
  categorySkill: 'Skills',
  categoryCustom: 'Your own variables',

  // Where a value is coming from.
  sourceProcess: 'process env',
  sourceCwdFile: 'project .env',
  sourceHomeFile: 'AgentOS .env',

  // Summary strip.
  statSet: 'Set',
  statSetTotal: '/{total}',
  statMissing: 'Missing',
  statShadowed: 'Shadowed',
  metaFile: 'File',
  shortPath: '…/{tail}',

  // Shadowing warning.
  shadowWarningTitle: '{count} variable(s) are shadowed by the process environment.',
  shadowWarningBody:
    'The shell that started the gateway exported them, and that value wins over the file. Editing them here will not take effect until the export is removed and the gateway restarts.',
  rowShadowed:
    'Shadowed by the process environment — changes here take effect only after the export is removed and the gateway restarts.',

  // Toolbar.
  search: 'Search variables',
  filterLandmark: 'Filter variables',
  filterAll: 'All',
  filterMissing: 'Missing',
  filterSet: 'Set',
  filterCustom: 'Custom',

  // List.
  loading: 'Loading variables…',
  emptyFiltered: 'No variables match this filter.',
  groupCount: '{set}/{total} set',
  tailShow: 'Show {count} unset',
  tailHide: 'Hide {count} unset',

  // Row.
  rowLockTitle:
    'Blocked by AgentOS security policy — edit ~/.agentos/.env directly if you genuinely need it.',
  rowLockLabel: 'Not writable through AgentOS',
  badgeSet: 'set',
  badgeMissing: 'missing',
  badgeUnset: 'unset',
  rowOwner: 'Needed by {owner}',
  rowLink: 'Where to get this',
  rowEdit: 'Edit',
  rowSet: 'Set',
  rowEditLabel: 'Edit {name}',
  rowSetLabel: 'Set {name}',
  rowImport: 'Use {source}',
  rowReveal: 'Reveal {name}',
  rowRemove: 'Remove {name}',
  rowValueLabel: 'Value for {name}',
  rowSave: 'Save',
  rowCancel: 'Cancel',

  // Add-a-variable dialog.
  addTitle: 'Add a variable',
  // Rendered around a <code>.env</code> element; see EnvPage.
  addBodyLead: 'Stored in the AgentOS',
  addBodyTail: 'and applied to the running gateway.',
  addNameLabel: 'Name',
  addNamePlaceholder: 'MY_SERVICE_TOKEN',
  addNameField: 'New variable name',
  addValueLabel: 'Value',
  addValueField: 'New variable value',
  addSave: 'Save',
  addCancel: 'Cancel',

  // Name validation.
  validateEmpty: 'Enter a variable name.',
  validateCharset: 'Use letters, digits, and underscores, starting with a letter or underscore.',
  validateReadOnly: 'This name cannot be written through AgentOS.',

  // Confirmations.
  confirmRevealTitle: 'Show {name}?',
  confirmRevealBody: 'The real value appears on screen and hides again after 30 seconds.',
  confirmRevealAction: 'Show value',
  confirmRemoveTitle: 'Remove {name}?',
  confirmRemoveBody: 'It is deleted from the AgentOS .env and from the running gateway.',
  confirmRemoveAction: 'Remove',
  confirmCancel: 'Cancel',

  // Load failure.
  loadErrorTitle: 'Environment unavailable',
  loadErrorRetry: 'Retry',

  // Toasts.
  toastSavedRestart: '{name} saved — restart the gateway for it to take full effect.',
  toastSaved: '{name} saved.',
  toastImported: "{name} imported. It will not follow that source's own rotation.",
  toastRemoved: '{name} removed.',
} as const
