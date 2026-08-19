// Chat transcript — exit_plan_mode plan card.
//
// AgentOS-native. Follows the ask-card end-turn contract (transcript/ask.ts):
// the backend terminates the turn after exit_plan_mode presents the plan, and
// approval is OUT OF BAND — the Approve button turns plan mode off via
// `plan.mode.set` and then sends the go-ahead as the next user message
// (injected as `approvePlan`). Typed feedback in the composer keeps plan mode
// on and refines the plan instead.
//
// The card carries the `.chat-ask-card` base class ON PURPOSE: the history
// renderer's lockAnsweredAskCards pass (ask.ts) then locks a plan card that
// already has a user message after it, the same way it locks answered
// questions — including this card in that sweep is what keeps a stale
// Approve button from inviting a click.

import { t } from '@/i18n'
import '@/i18n/en/chat'

import type { StreamEventPayload } from '../types'

const PLAN_TOOL_NAME = 'exit_plan_mode'
const PLAN_STATUS_PRESENTED = 'plan_presented'

/* ── Pure helper (unit-tested) ──────────────────────────────────────────── */

/**
 * Extract the presented plan from an exit_plan_mode `tool_result` frame.
 * Returns null for other tools, error results, or malformed payloads.
 */
export function parsePlanFromToolResult(payload: StreamEventPayload): string | null {
  const p = payload as {
    name?: string
    tool_name?: string
    is_error?: boolean
    isError?: boolean
    result?: unknown
  }
  const toolName = p.name || p.tool_name || ''
  if (toolName !== PLAN_TOOL_NAME || p.is_error || p.isError) return null
  let parsed: unknown = p.result
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed)
    } catch {
      return null
    }
  }
  if (!parsed || typeof parsed !== 'object') return null
  const body = parsed as { status?: unknown; plan?: unknown }
  if (body.status !== PLAN_STATUS_PRESENTED) return null
  const plan = typeof body.plan === 'string' ? body.plan.trim() : ''
  return plan || null
}

/* ── Imperative DOM builder (composed by the tool renderer) ─────────────── */

export function buildPlanCardDOM(
  plan: string,
  approvePlan: (() => boolean) | undefined,
): HTMLElement {
  const card = document.createElement('div')
  card.className = 'chat-ask-card chat-plan-card'
  card.setAttribute('role', 'group')
  card.setAttribute('aria-label', t('chat.planCardLabel'))

  const eyebrow = document.createElement('div')
  eyebrow.className = 'chat-ask-eyebrow'
  eyebrow.textContent = t('chat.planCardLabel')
  card.appendChild(eyebrow)

  const body = document.createElement('div')
  body.className = 'chat-plan-body'
  body.textContent = plan
  card.appendChild(body)

  const footer = document.createElement('div')
  footer.className = 'chat-ask-footer chat-plan-footer'
  const approveBtn = document.createElement('button')
  approveBtn.type = 'button'
  approveBtn.className = 'btn btn--sm chat-ask-send chat-plan-approve'
  approveBtn.textContent = t('chat.planApprove')
  if (!approvePlan) approveBtn.disabled = true
  let answered = false
  approveBtn.addEventListener('click', () => {
    if (answered || !approvePlan) return
    // The approver reports whether the approval actually went out (false
    // while the ended turn's stream is still settling).
    if (!approvePlan()) return
    answered = true
    card.classList.add('chat-ask-card--answered')
    card.querySelectorAll<HTMLButtonElement>('button').forEach((el) => {
      el.disabled = true
    })
    const done = document.createElement('div')
    done.className = 'chat-ask-answered'
    done.textContent = t('chat.planApproved')
    card.appendChild(done)
  })
  footer.appendChild(approveBtn)
  const hint = document.createElement('span')
  hint.className = 'chat-plan-refine-hint'
  hint.textContent = t('chat.planRefineHint')
  footer.appendChild(hint)
  card.appendChild(footer)

  return card
}
