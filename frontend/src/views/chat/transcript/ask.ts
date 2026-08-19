// Chat transcript — ask_user interactive question card.
//
// AgentOS-native (no legacy chat.js counterpart). The ask_user tool follows
// an end-turn-and-resume contract: the backend terminates the turn after the
// tool runs and the user's answer arrives as the next user message. This
// module renders the presented questions as a clickable card in the live
// stream bubble; clicking sends the composed answer through the same
// `chat.send` path the composer uses (injected as `sendAnswer`). Typing a
// free-text reply in the composer always works too — the card is a
// convenience, not the mechanism.
//
// Split mirrors tools.ts: pure parse/compose helpers (unit-tested in
// ask.test.ts) + an imperative DOM builder composed by the tool renderer.

import { t } from '@/i18n'
import '@/i18n/en/chat'

import type { StreamEventPayload } from '../types'

export interface AskOption {
  label: string
  description?: string
}

export interface AskQuestion {
  question: string
  header?: string
  options: AskOption[]
  multiSelect: boolean
}

/* ── Pure helpers (unit-tested) ─────────────────────────────────────────── */

const ASK_TOOL_NAME = 'ask_user'
const ASK_STATUS_PRESENTED = 'question_presented'

/**
 * Parse presented questions from an ask_user `tool_result` stream frame.
 * Returns null for other tools, error results, or malformed payloads —
 * rendering keys off the RESULT (not the arguments) so a validation
 * failure never draws a half-formed card.
 */
export function parseAskQuestions(payload: StreamEventPayload): AskQuestion[] | null {
  const p = payload as {
    name?: string
    tool_name?: string
    is_error?: boolean
    isError?: boolean
    result?: unknown
  }
  const toolName = p.name || p.tool_name || ''
  if (toolName !== ASK_TOOL_NAME || p.is_error || p.isError) return null
  let parsed: unknown = p.result
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed)
    } catch {
      return null
    }
  }
  if (!parsed || typeof parsed !== 'object') return null
  const body = parsed as { status?: unknown; questions?: unknown }
  if (body.status !== ASK_STATUS_PRESENTED || !Array.isArray(body.questions)) return null

  const questions: AskQuestion[] = []
  for (const raw of body.questions) {
    if (!raw || typeof raw !== 'object') return null
    const q = raw as {
      question?: unknown
      header?: unknown
      options?: unknown
      multi_select?: unknown
    }
    const question = typeof q.question === 'string' ? q.question.trim() : ''
    if (!question || !Array.isArray(q.options)) return null
    const options: AskOption[] = []
    for (const rawOpt of q.options) {
      if (!rawOpt || typeof rawOpt !== 'object') return null
      const opt = rawOpt as { label?: unknown; description?: unknown }
      const label = typeof opt.label === 'string' ? opt.label.trim() : ''
      if (!label) return null
      const option: AskOption = { label }
      if (typeof opt.description === 'string' && opt.description.trim()) {
        option.description = opt.description.trim()
      }
      options.push(option)
    }
    if (options.length < 2) return null
    const entry: AskQuestion = {
      question,
      options,
      multiSelect: q.multi_select === true,
    }
    if (typeof q.header === 'string' && q.header.trim()) entry.header = q.header.trim()
    questions.push(entry)
  }
  return questions.length > 0 ? questions : null
}

/**
 * Compose the outgoing user message from per-question selections plus an
 * optional free-text addition. Single question → just the answer text;
 * multiple questions → one `Header: answer` line per answered question.
 */
export function composeAskAnswer(
  questions: AskQuestion[],
  selections: string[][],
  freeText = '',
): string {
  const lines: string[] = []
  const multi = questions.length > 1
  questions.forEach((q, i) => {
    const chosen = (selections[i] || []).filter(Boolean)
    if (chosen.length === 0) return
    const answer = chosen.join(', ')
    lines.push(multi ? `${q.header || q.question}: ${answer}` : answer)
  })
  const extra = freeText.trim()
  if (extra) lines.push(extra)
  return lines.join('\n')
}

/**
 * Mark ask cards that already have a user message after them as answered and
 * disable their controls. History reconstruction rebuilds bubbles from
 * persisted segments, so a card that was answered in a previous turn would
 * otherwise come back active.
 */
export function lockAnsweredAskCards(container: HTMLElement): void {
  container
    .querySelectorAll<HTMLElement>('.chat-ask-card:not(.chat-ask-card--answered)')
    .forEach((card) => {
      const row = card.closest<HTMLElement>('.msg')
      if (!row) return
      let el = row.nextElementSibling
      while (el) {
        const isUserRow =
          el.classList.contains('user') || el.getAttribute('data-history-role') === 'user'
        if (isUserRow) {
          card.classList.add('chat-ask-card--answered')
          card
            .querySelectorAll<HTMLButtonElement | HTMLInputElement>('button, input')
            .forEach((c) => {
              c.disabled = true
            })
          return
        }
        el = el.nextElementSibling
      }
    })
}

/* ── Imperative DOM builder (composed by the tool renderer) ─────────────── */

export function buildAskCardDOM(
  questions: AskQuestion[],
  sendAnswer: ((text: string) => boolean) | undefined,
): HTMLElement {
  const card = document.createElement('div')
  card.className = 'chat-ask-card'
  card.setAttribute('role', 'group')
  card.setAttribute('aria-label', t('chat.askCardLabel'))

  // selections[qi] = list of selected labels for question qi.
  const selections: string[][] = questions.map(() => [])
  let answered = false

  const eyebrow = document.createElement('div')
  eyebrow.className = 'chat-ask-eyebrow'
  eyebrow.textContent = t('chat.askCardLabel')
  card.appendChild(eyebrow)

  // One-question single-select cards send on click; everything else
  // toggles selections and submits through the Send button.
  const instantSend = questions.length === 1 && !questions[0]?.multiSelect && !!sendAnswer

  // Free-text alternative, created in the footer below; declared ahead of
  // `submit` so the closure reads the assigned input at click time.
  let otherInput: HTMLInputElement | null = null

  const submit = (): void => {
    if (answered || !sendAnswer) return
    const text = composeAskAnswer(questions, selections, otherInput ? otherInput.value : '')
    if (!text) return
    // The sender reports whether the message actually went out (false while
    // the stream is still settling); only then does the card lock itself.
    if (!sendAnswer(text)) return
    answered = true
    card.classList.add('chat-ask-card--answered')
    card.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button, input').forEach((el) => {
      el.disabled = true
    })
    const done = document.createElement('div')
    done.className = 'chat-ask-answered'
    done.textContent = `${t('chat.askAnswered')}: ${text}`
    card.appendChild(done)
  }

  questions.forEach((q, qi) => {
    const block = document.createElement('div')
    block.className = 'chat-ask-question'

    const title = document.createElement('div')
    title.className = 'chat-ask-title'
    if (q.header) {
      const chip = document.createElement('span')
      chip.className = 'chat-ask-header-chip'
      chip.textContent = q.header
      title.appendChild(chip)
    }
    title.appendChild(document.createTextNode(q.question))
    block.appendChild(title)

    if (q.multiSelect) {
      const hint = document.createElement('div')
      hint.className = 'chat-ask-multi-hint'
      hint.textContent = t('chat.askMultiHint')
      block.appendChild(hint)
    }

    const optionRow = document.createElement('div')
    optionRow.className = 'chat-ask-options'
    q.options.forEach((opt) => {
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'chat-ask-option'
      if (!sendAnswer) btn.disabled = true
      const label = document.createElement('span')
      label.className = 'chat-ask-option-label'
      label.textContent = opt.label
      btn.appendChild(label)
      if (opt.description) {
        const desc = document.createElement('span')
        desc.className = 'chat-ask-option-desc'
        desc.textContent = opt.description
        btn.appendChild(desc)
        btn.title = opt.description
      }
      btn.addEventListener('click', () => {
        if (answered) return
        if (instantSend) {
          selections[qi] = [opt.label]
          submit()
          return
        }
        let current = selections[qi]
        if (!current) {
          current = []
          selections[qi] = current
        }
        const at = current.indexOf(opt.label)
        if (q.multiSelect) {
          if (at >= 0) current.splice(at, 1)
          else current.push(opt.label)
          btn.classList.toggle('chat-ask-option--selected', at < 0)
        } else {
          selections[qi] = [opt.label]
          optionRow
            .querySelectorAll('.chat-ask-option--selected')
            .forEach((el) => el.classList.remove('chat-ask-option--selected'))
          btn.classList.add('chat-ask-option--selected')
        }
      })
      optionRow.appendChild(btn)
    })
    block.appendChild(optionRow)
    card.appendChild(block)
  })

  // Free-text alternative: always offered, so the card never traps the user
  // in the listed options.
  const footer = document.createElement('div')
  footer.className = 'chat-ask-footer'
  otherInput = document.createElement('input')
  otherInput.type = 'text'
  otherInput.className = 'chat-ask-other'
  otherInput.placeholder = t('chat.askOtherPlaceholder')
  if (!sendAnswer) otherInput.disabled = true
  otherInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      submit()
    }
  })
  footer.appendChild(otherInput)
  if (!instantSend) {
    const sendBtn = document.createElement('button')
    sendBtn.type = 'button'
    sendBtn.className = 'btn btn--sm chat-ask-send'
    sendBtn.textContent = t('chat.askSend')
    if (!sendAnswer) sendBtn.disabled = true
    sendBtn.addEventListener('click', submit)
    footer.appendChild(sendBtn)
  }
  card.appendChild(footer)

  return card
}
