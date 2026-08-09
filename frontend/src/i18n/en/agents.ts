import { defineNamespace } from '../registry'

export const agents = defineNamespace('agents', {
  documentTitle: 'Agents - AgentOS Control',
  eyebrow: 'Control · Agents',
  title: 'Agents',
  subtitle: 'Custom personalities and skill sets you can chat with.',
  refresh: 'Refresh',
  newAgent: 'New agent',

  // Summary tiles.
  statsLandmark: 'Agents summary',
  statTotal: 'Total agents',
  statBuiltinCount: '{count} built-in',
  statCustomCount: '{count} custom',
  statNoneConfigured: 'none configured',
  statModels: 'Models in use',
  statModelsHint: 'distinct models',
  statModelsUnset: 'unset',
  statTools: 'Tools wired',
  statToolsHint: 'across all agents',

  // Card.
  cardLandmark: 'Agent {id}',
  cardModel: 'Model',
  cardTools: 'Tools',
  cardSkills: 'Skills',
  cardChat: 'Chat',
  cardCustomizeTitle: 'Use as a starting point for a new agent',
  cardCustomize: 'Customize',
  cardEdit: 'Edit',
  cardDelete: 'Delete',
  copyName: '{id} (copy)',

  // List.
  listTitle: 'Configured agents',
  emptyTitle: 'No agents configured.',
  // The empty-state sentence wraps two inline elements (a <strong> for the
  // button name and a <code> for the agent id), so it is stored as the three
  // runs of text between them rather than one string with markup in it.
  emptyMsgLead: 'Use',
  emptyMsgMiddle: 'above to add one. The default',
  emptyMsgTail: 'agent is always available.',

  // Create / edit dialog.
  dialogCreateTitle: 'New agent',
  dialogEditTitle: 'Edit agent: {id}',
  fieldId: 'Agent ID',
  fieldIdPlaceholder: 'e.g. data-analyst',
  fieldIdRequired: 'Agent ID is required.',
  fieldName: 'Display name',
  fieldNamePlaceholder: 'Defaults to ID',
  createHint:
    "Created agents inherit the global default model. Add tools and other capabilities after creating from the agent's Edit dialog.",
  fieldDescription: 'Description',
  fieldDescriptionPlaceholder: 'A short one-liner',
  advancedSummary: 'Capabilities · Advanced',
  fieldTools: 'Tools (comma-separated)',
  fieldToolsPlaceholder: 'Leave blank to inherit defaults',
  fieldWorkspace: 'Workspace',
  fieldWorkspacePlaceholder: 'Leave blank to use the default path',
  fieldAgentDir: 'Agent dir',
  fieldAgentDirPlaceholder: 'Optional',
  fieldEnabled: 'Enabled',
  submitCreate: 'Create agent',
  submitSave: 'Save changes',

  // Confirmations.
  discardTitle: 'Discard unsaved changes?',
  discardBody: 'You have unsaved edits. Closing now will lose them.',
  discardConfirm: 'Discard',
  discardCancel: 'Keep editing',
  deleteTitle: 'Delete agent',
  deleteBodyLead: 'Delete agent',
  deleteBodyTail: '? Existing chats with this agent will keep working but become unmanaged.',
  deleteConfirm: 'Delete agent',

  // Toasts.
  toastLoadFailed: 'Failed to load agents: {message}',
  toastCreated: 'Agent created: {id}',
  toastExists: 'Agent "{id}" already exists',
  toastCreateFailed: 'Failed to create agent: {message}',
  toastUpdated: 'Agent updated: {id}',
  toastSaveFailed: 'Failed to save: {message}',
  toastNotFound: 'Agent "{id}" no longer exists.',
  toastBuiltinImmutable: '"{id}" is a built-in agent and cannot be modified.',
  toastDeleted: 'Agent deleted: {id}',
  toastDeleteFailed: 'Failed to delete agent: {message}',
  toastNothingToSave: 'Nothing to save',
} as const)
