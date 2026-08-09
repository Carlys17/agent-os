import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_LOCALE,
  formatNumber,
  getLocale,
  registerCatalog,
  resolveLocale,
  setLocale,
  t,
  tPlural,
} from './index'
import type { MessageKey } from './types'

// A stub locale registered once, deliberately incomplete: it overrides a single
// key and omits a whole namespace, so both rungs of the fallback ladder are
// exercised against real catalog data rather than a mock.
registerCatalog('xx', { common: { save: 'XX save' } })

// A second stub, under a real tag whose grouping and decimal marks differ from
// English, so the number assertions below are about `Intl` rather than about an
// invented tag quietly resolving to the runtime default. Its one template
// carries the placeholder names the exemption rule has to tell apart.
registerCatalog('de', {
  common: { save: 'Port {socketPort} · Sitzung {sessionId} · {count} offen · {ratio}' },
})

/** `common.save` takes no vars in `en`, so the stub template's vars need a cast. */
const tStub = t as (key: MessageKey, vars: Record<string, string | number>) => string

afterEach(() => {
  setLocale(DEFAULT_LOCALE)
})

describe('t', () => {
  it('returns the English string for a known key', () => {
    expect(t('common.save')).toBe('Save')
    expect(getLocale()).toBe('en')
  })

  it('interpolates a placeholder', () => {
    expect(t('overview.toastStatusFailed', { message: 'boom' })).toBe('Failed to load status: boom')
  })

  it('interpolates numbers and multiple placeholders', () => {
    expect(t('overview.uptime', { hours: 1, minutes: 2, seconds: 3 })).toBe('1h 2m 3s')
    expect(t('env.groupCount', { set: 2, total: 7 })).toBe('2/7 set')
  })

  it('leaves an unknown token literal rather than rendering undefined', () => {
    // The vars object is deliberately missing `version`, which the type system
    // would normally reject — the runtime must still not print "undefined".
    const vars = {} as { version: string }
    expect(t('overview.tileVersion', vars)).toBe('v{version}')
  })

  it('returns the key itself and warns when the key is unknown', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(t('common.nope' as MessageKey)).toBe('common.nope')
    expect(warn).toHaveBeenCalledWith('[i18n] missing key: common.nope')
    warn.mockRestore()
  })

  it('falls back to English for a key the active locale omits', () => {
    setLocale('xx')
    expect(t('common.save')).toBe('XX save')
    // Present in the namespace it overrides, but not translated.
    expect(t('common.cancel')).toBe('Cancel')
  })

  it('falls back to English for a namespace the active locale omits entirely', () => {
    setLocale('xx')
    expect(t('shell.viewOverview')).toBe('Overview')
  })
})

describe('registerCatalog', () => {
  it('rejects a tag Intl.PluralRules would reject, and registers nothing', () => {
    // The issue's exact case: an underscore instead of a hyphen used to register
    // cleanly and then kill the first pluralised string in an unrelated view.
    expect(() => registerCatalog('pt_BR', {})).toThrow(RangeError)
    expect(() => registerCatalog('', {})).toThrow(RangeError)
    expect(() => registerCatalog('nope', {})).toThrow(RangeError)
    expect(resolveLocale('pt_BR')).toBe('en')
  })

  it('folds non-canonical casing onto a single entry', () => {
    registerCatalog('YY-zz', { common: { save: 'first' } })
    registerCatalog('yy-ZZ', { common: { save: 'second' } })
    // A second entry would have left the first one reachable.
    setLocale('yy-ZZ')
    expect(t('common.save')).toBe('second')
    expect(resolveLocale('YY-ZZ')).toBe('yy-zz')
    expect(resolveLocale('yy_zz')).toBe('yy-zz')
  })

  it('canonicalises a deprecated tag to its modern form', () => {
    registerCatalog('iw', {})
    expect(resolveLocale('he')).toBe('he')
  })

  it('leaves every registered tag safe for Intl.PluralRules', () => {
    registerCatalog('zh-hant-cn', {})
    setLocale('zh-Hant-CN')
    expect(() => tPlural('overview.eventsCount', 3)).not.toThrow()
  })
})

describe('numeric interpolation', () => {
  it('groups a quantity for the active locale', () => {
    expect(t('env.statSetTotal', { total: 1234567 })).toBe('/1,234,567')
    setLocale('de')
    expect(t('env.statSetTotal', { total: 1234567 })).toBe('/1.234.567')
  })

  it('renders decimals with the active locale separator', () => {
    expect(t('health.railCountShare', { percent: 12.5 })).toBe('12.5%')
    setLocale('de')
    expect(t('health.railCountShare', { percent: 12.5 })).toBe('12,5%')
  })

  it('leaves identifiers and machine codes ungrouped in every locale', () => {
    // `HTTP 1,001` and `Finding 1,024` are wrong everywhere, not just in English.
    expect(t('shell.errorHttpCode', { status: 1001 })).toBe('HTTP 1001')
    expect(t('health.findingFallbackTitle', { index: 1024 })).toBe('Finding 1024')
    setLocale('de')
    expect(t('shell.errorHttpCode', { status: 1001 })).toBe('HTTP 1001')
    expect(t('health.findingFallbackTitle', { index: 1024 })).toBe('Finding 1024')
  })

  it('reads the exemption off the last word of the placeholder name', () => {
    // `socketPort` and `sessionId` are exempt without being named anywhere;
    // `count` and `ratio` next to them still take the locale's marks.
    setLocale('de')
    expect(
      tStub('common.save', { socketPort: 8080, sessionId: 1024, count: 1024, ratio: 1.5 }),
    ).toBe('Port 8080 · Sitzung 1024 · 1.024 offen · 1,5')
  })

  it('leaves strings alone, so a pre-formatted value is not formatted twice', () => {
    setLocale('de')
    expect(t('overview.tileSpent', { amount: '$1,234.50' })).toBe('$1,234.50 spent')
  })

  it('falls back to String for non-finite numbers', () => {
    // An upstream NaN should read as "NaN", not as a localised "∞".
    expect(t('health.railCountShare', { percent: Number.NaN })).toBe('NaN%')
    expect(t('health.railCountShare', { percent: Number.POSITIVE_INFINITY })).toBe('Infinity%')
  })
})

describe('formatNumber', () => {
  it('formats for the active locale, not the browser default', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
    setLocale('de')
    expect(formatNumber(1234567)).toBe('1.234.567')
  })

  it('matches what the same number renders as inside a template', () => {
    // The counters rendered outside `t()` sit next to ones rendered through it;
    // a tile whose value and caption disagree on the separator is the bug.
    setLocale('de')
    expect(t('env.statSetTotal', { total: 2000 })).toBe(`/${formatNumber(2000)}`)
  })

  it('passes non-finite values through unformatted', () => {
    expect(formatNumber(Number.NaN)).toBe('NaN')
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe('Infinity')
  })
})

describe('resolveLocale', () => {
  it('defaults to English for empty, nullish, and unknown input', () => {
    expect(resolveLocale('')).toBe('en')
    expect(resolveLocale(null)).toBe('en')
    expect(resolveLocale(undefined)).toBe('en')
    expect(resolveLocale('  ')).toBe('en')
    expect(resolveLocale('zz')).toBe('en')
  })

  it('is case-insensitive and falls back to the primary subtag', () => {
    expect(resolveLocale('EN')).toBe('en')
    expect(resolveLocale('en-US')).toBe('en')
    expect(resolveLocale('xx_YZ')).toBe('xx')
  })

  it('resolves an unregistered region to English, not to the region tag', () => {
    expect(resolveLocale('pt-BR')).toBe('en')
  })
})

describe('setLocale', () => {
  it('applies the resolved locale and mirrors it onto <html lang>', () => {
    expect(setLocale('xx')).toBe('xx')
    expect(getLocale()).toBe('xx')
    expect(document.documentElement.lang).toBe('xx')
  })

  it('resolves unknown input to English rather than throwing', () => {
    expect(setLocale('nope')).toBe('en')
    expect(getLocale()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })
})

describe('tPlural', () => {
  it('selects the singular for exactly one', () => {
    expect(tPlural('shell.navApprovalBadge', 1)).toBe('1 pending approval')
  })

  it('selects the plural for zero and for many', () => {
    expect(tPlural('shell.navApprovalBadge', 0)).toBe('0 pending approvals')
    expect(tPlural('shell.navApprovalBadge', 3)).toBe('3 pending approvals')
    expect(tPlural('overview.eventsCount', 12)).toBe('12 events')
  })

  it('groups the injected count', () => {
    expect(tPlural('overview.eventsCount', 1234)).toBe('1,234 events')
    setLocale('de')
    expect(tPlural('overview.eventsCount', 1234)).toBe('1.234 events')
  })

  it('degrades to _other for a category no catalog defines', () => {
    // Polish selects 'few' for 3. No catalog has an `_few` key, so the lookup
    // must fall through to `_other` rather than rendering the raw key.
    registerCatalog('pl', {})
    setLocale('pl')
    expect(new Intl.PluralRules('pl').select(3)).toBe('few')
    expect(tPlural('overview.eventsCount', 3)).toBe('3 events')
  })
})
