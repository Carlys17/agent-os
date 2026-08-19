// Unit tests for the ask_user card's pure helpers (transcript/ask.ts).
// The DOM builder follows the tools.ts convention: verified by the
// live-browser sweep, not RTL — only parse/compose logic is tested here.
import { describe, expect, it } from 'vitest'

import { composeAskAnswer, parseAskQuestions, type AskQuestion } from './ask'

const presented = (questions: unknown): string =>
  JSON.stringify({ status: 'question_presented', questions })

const q = (over: Partial<Record<string, unknown>> = {}): Record<string, unknown> => ({
  question: 'Deploy now?',
  options: [{ label: 'Yes' }, { label: 'No', description: 'wait for CI' }],
  multi_select: false,
  ...over,
})

describe('parseAskQuestions', () => {
  it('parses a presented ask_user result into normalized questions', () => {
    const out = parseAskQuestions({
      tool_name: 'ask_user',
      result: presented([q({ header: 'Deploy' })]),
    })
    expect(out).toEqual([
      {
        question: 'Deploy now?',
        header: 'Deploy',
        options: [{ label: 'Yes' }, { label: 'No', description: 'wait for CI' }],
        multiSelect: false,
      },
    ])
  })

  it('accepts the name alias and multi_select flag', () => {
    const out = parseAskQuestions({
      name: 'ask_user',
      result: presented([q({ multi_select: true })]),
    })
    expect(out?.[0]?.multiSelect).toBe(true)
  })

  it('returns null for other tools, error results, and non-presented payloads', () => {
    expect(parseAskQuestions({ tool_name: 'exec_command', result: presented([q()]) })).toBeNull()
    expect(
      parseAskQuestions({ tool_name: 'ask_user', is_error: true, result: presented([q()]) }),
    ).toBeNull()
    expect(
      parseAskQuestions({ tool_name: 'ask_user', result: JSON.stringify({ status: 'error' }) }),
    ).toBeNull()
    expect(parseAskQuestions({ tool_name: 'ask_user', result: 'not json' })).toBeNull()
  })

  it('rejects malformed questions rather than rendering a partial card', () => {
    expect(
      parseAskQuestions({ tool_name: 'ask_user', result: presented([q({ question: '' })]) }),
    ).toBeNull()
    expect(
      parseAskQuestions({
        tool_name: 'ask_user',
        result: presented([q({ options: [{ label: 'only one' }] })]),
      }),
    ).toBeNull()
    expect(
      parseAskQuestions({
        tool_name: 'ask_user',
        result: presented([q({ options: [{ label: 'a' }, { label: '' }] })]),
      }),
    ).toBeNull()
    expect(parseAskQuestions({ tool_name: 'ask_user', result: presented([]) })).toBeNull()
  })
})

describe('composeAskAnswer', () => {
  const deployQuestion: AskQuestion = {
    question: 'Deploy now?',
    options: [{ label: 'Yes' }, { label: 'No' }],
    multiSelect: false,
  }
  const single: AskQuestion[] = [deployQuestion]
  const multi: AskQuestion[] = [
    { ...deployQuestion, header: 'Deploy' },
    {
      question: 'Which environment?',
      options: [{ label: 'staging' }, { label: 'prod' }],
      multiSelect: true,
    },
  ]

  it('returns just the answer for a single question', () => {
    expect(composeAskAnswer(single, [['Yes']])).toBe('Yes')
  })

  it('prefixes header (or question) per line for multiple questions', () => {
    expect(composeAskAnswer(multi, [['Yes'], ['staging', 'prod']])).toBe(
      'Deploy: Yes\nWhich environment?: staging, prod',
    )
  })

  it('skips unanswered questions and appends trimmed free text', () => {
    expect(composeAskAnswer(multi, [[], ['staging']], '  canary first  ')).toBe(
      'Which environment?: staging\ncanary first',
    )
  })

  it('returns empty when nothing was chosen or typed', () => {
    expect(composeAskAnswer(single, [[]], '   ')).toBe('')
  })
})
