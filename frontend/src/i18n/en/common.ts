import { defineNamespace } from '../registry'

/**
 * Shared copy that recurs across views. Anything view-specific belongs in that
 * view's own namespace module, not here.
 */
export const common = defineNamespace('common', {
  cancel: 'Cancel',
  close: 'Close',
  copy: 'Copy',
  dash: '—',
  loading: 'Loading…',
  retry: 'Retry',
  save: 'Save',
} as const)
