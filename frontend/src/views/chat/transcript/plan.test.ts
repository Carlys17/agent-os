// Unit tests for the plan card's pure helper (transcript/plan.ts). The DOM
// builder follows the tools.ts convention: live-browser sweep, not RTL.
import { describe, expect, it } from 'vitest'

import { parsePlanFromToolResult } from './plan'

const presented = (plan: unknown): string => JSON.stringify({ status: 'plan_presented', plan })

describe('parsePlanFromToolResult', () => {
  it('extracts the plan from a presented exit_plan_mode result', () => {
    expect(
      parsePlanFromToolResult({ tool_name: 'exit_plan_mode', result: presented('## Plan\n1. X') }),
    ).toBe('## Plan\n1. X')
  })

  it('accepts the name alias', () => {
    expect(parsePlanFromToolResult({ name: 'exit_plan_mode', result: presented('X') })).toBe('X')
  })

  it('returns null for other tools, errors, and malformed payloads', () => {
    expect(parsePlanFromToolResult({ tool_name: 'ask_user', result: presented('X') })).toBeNull()
    expect(
      parsePlanFromToolResult({
        tool_name: 'exit_plan_mode',
        is_error: true,
        result: presented('X'),
      }),
    ).toBeNull()
    expect(parsePlanFromToolResult({ tool_name: 'exit_plan_mode', result: 'not json' })).toBeNull()
    expect(
      parsePlanFromToolResult({
        tool_name: 'exit_plan_mode',
        result: JSON.stringify({ status: 'error' }),
      }),
    ).toBeNull()
    expect(
      parsePlanFromToolResult({ tool_name: 'exit_plan_mode', result: presented('   ') }),
    ).toBeNull()
  })
})
