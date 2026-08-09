import { t } from '@/i18n'
import '@/i18n/en/chat'

import { toast } from 'sonner'

interface SessionResetRpc {
  call(method: string, params?: Record<string, unknown>): Promise<unknown>
}

interface CodedError {
  code?: unknown
  message?: unknown
}

function errorCode(error: unknown): string {
  if (!error || typeof error !== 'object') return ''
  const code = (error as CodedError).code
  return typeof code === 'string' ? code : ''
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (error && typeof error === 'object') {
    const message = (error as CodedError).message
    if (typeof message === 'string') return message
  }
  return String(error)
}

async function discardAndReset(rpc: SessionResetRpc, sessionKey: string): Promise<void> {
  try {
    await rpc.call('sessions.reset', { key: sessionKey, force: true })
    toast.info(t('chat.resetNoBackup'))
  } catch (error) {
    if (errorCode(error) === 'permission_denied') {
      toast.error(t('chat.resetNoBackupDenied'))
      return
    }
    toast.error(t('chat.resetFailed', { message: errorMessage(error) }))
  }
}

/**
 * Reset through the safe flush path first. If transcript backup is disabled,
 * offer the connected Control client an explicit destructive recovery action instead of
 * leaking the backend-only `force=true` instruction into the UI.
 */
export async function resetSession(rpc: SessionResetRpc, sessionKey: string): Promise<void> {
  try {
    await rpc.call('sessions.reset', { key: sessionKey })
    toast.info(t('chat.resetDone'))
  } catch (error) {
    if (errorCode(error) === 'flush_unavailable') {
      toast.warning(t('chat.resetBackupUnavailable'), {
        id: 'session-reset-flush-unavailable',
        description: t('chat.resetBackupPrompt'),
        duration: Infinity,
        action: {
          label: t('chat.resetDiscardAction'),
          onClick: () => {
            void discardAndReset(rpc, sessionKey)
          },
        },
      })
      return
    }
    toast.error(t('chat.resetFailed', { message: errorMessage(error) }))
  }
}
