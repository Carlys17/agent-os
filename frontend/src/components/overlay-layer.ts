// One place that answers "is a modal or popover on screen right now?".
//
// Document-level key handlers each used to carry their own hardcoded selector
// list ('.modal-backdrop, .chat-session-popover, .chat-session-actions-menu'),
// so every new dialog had to remember to extend every list. They drifted: the
// chat handler still guarded on `.modal-backdrop`, which no view renders any
// more, and knew about none of the tokenised `*-modal__overlay` dialogs — the
// blocking approval prompt included.
//
// Layers register themselves instead. `ModalShell` covers every tokenised
// dialog (agents / sessions / skills / cron / env / mcp / channels / approvals
// / the shortcut overlay); the chat session popover, which is not a ModalShell,
// opts in explicitly.
import { useEffect } from 'react'

let depth = 0

/** How many overlay layers are mounted right now. */
export function overlayDepth(): number {
  return depth
}

/**
 * Count this component as an overlay layer while `active`.
 *
 * Reads are synchronous (`overlayDepth()`), so a document-level keydown handler
 * can consult it without subscribing and re-binding.
 */
export function useOverlayLayer(active: boolean = true): void {
  useEffect(() => {
    if (!active) return
    depth += 1
    return () => {
      // Clamp: a double-invoked cleanup (StrictMode) must not drive the count
      // negative and silently disable every guard that reads it.
      depth = Math.max(0, depth - 1)
    }
  }, [active])
}
