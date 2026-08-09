import { defineNamespace } from '../registry'

export const settings = defineNamespace('settings', {
  documentTitle: 'Agent Setup - AgentOS Control',
  eyebrow: 'Control · Settings',
  title: 'Agent Setup',
  subtitle: 'Choose the model, routing, and tools this agent can use.',

  // Header status pill + refresh control.
  statusChangesPaused: 'Changes paused',
  statusRestartNeeded: 'Restart needed',
  statusUnavailable: 'Status unavailable',
  statusChecking: 'Checking setup',
  statusReady: 'Ready to use',
  setupItemsLeft_one: '{count} setup item left',
  setupItemsLeft_other: '{count} setup items left',
  refreshTitle: 'Refresh agent state',
  refreshBusy: 'Refreshing…',
  refresh: 'Refresh',

  // Guided / Advanced tablist.
  toolbarLandmark: 'Settings workspace',
  tabsLandmark: 'Settings mode',
  tabGuided: 'Guided setup',
  tabGuidedNote: 'Recommended',
  tabAdvanced: 'Advanced',
  tabAdvancedNote: 'Edit config',

  // "At a glance" strip.
  glanceLandmark: 'Current agent setup',
  glanceProgress: 'Setup progress',
  readinessCount: '{ready} of {total} ready',
  providerUnset: 'Provider not connected',
  modelUnset: 'Choose a model',
  glanceEnvironment: 'Environment',
  envCount: '{set} of {total} set',
  envManage: 'Manage variables',

  // Blocking banners.
  divergedBody:
    'The config file changed outside AgentOS. Writes are blocked until the gateway reloads or restarts with that file.',
  divergedAction: 'Refresh state',
  loadErrorBody:
    'Agent state could not be loaded. Retry before changing guided or advanced settings.',
} as const)
