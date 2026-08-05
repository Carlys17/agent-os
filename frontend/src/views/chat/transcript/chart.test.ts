// Pure-helper tests for the chart-artifact renderer (chart.ts).
//
// The imperative mounter draws through lightweight-charts against a real canvas
// and is covered by the live-browser sweep, not here. What IS covered here is
// everything that decides WHAT gets drawn: mime matching, payload
// normalization, the ordering/dedup contract lightweight-charts asserts on, and
// the price precision that keeps sub-cent meme tokens readable.

import { describe, it, expect } from 'vitest'
import {
  CHART_ARTIFACT_MIME,
  chartTheme,
  hasVolume,
  isChartArtifact,
  normalizeChartPayload,
  priceDecimals,
  volumeSeriesData,
} from './chart'

/* ── isChartArtifact ────────────────────────────────────────────────────── */

describe('isChartArtifact', () => {
  it('matches the chart mime', () => {
    expect(isChartArtifact({ mime: CHART_ARTIFACT_MIME })).toBe(true)
  })
  it('matches case-insensitively and ignores mime parameters', () => {
    expect(isChartArtifact({ mime: 'APPLICATION/VND.AGENTOS.CHART+JSON' })).toBe(true)
    expect(isChartArtifact({ mime: `${CHART_ARTIFACT_MIME}; charset=utf-8` })).toBe(true)
  })
  it('does not match plain JSON or a missing mime', () => {
    expect(isChartArtifact({ mime: 'application/json' })).toBe(false)
    expect(isChartArtifact({})).toBe(false)
    expect(isChartArtifact(null)).toBe(false)
  })
})

/* ── normalizeChartPayload ──────────────────────────────────────────────── */

const candle = (time: number, close = 1): Record<string, unknown> => ({
  time,
  open: 1,
  high: 2,
  low: 0.5,
  close,
})

describe('normalizeChartPayload', () => {
  it('returns null for non-objects and payloads without a candle array', () => {
    expect(normalizeChartPayload(null)).toBeNull()
    expect(normalizeChartPayload('nope')).toBeNull()
    expect(normalizeChartPayload({})).toBeNull()
    expect(normalizeChartPayload({ candles: 'no' })).toBeNull()
  })

  it('returns null when every candle is unusable', () => {
    expect(normalizeChartPayload({ candles: [{ time: 1 }, null, { open: 1 }] })).toBeNull()
  })

  it('keeps title and subtitle as trimmed strings', () => {
    const payload = normalizeChartPayload({
      title: '  BONK · 1h  ',
      subtitle: ' SOL ',
      candles: [candle(100)],
    })
    expect(payload?.title).toBe('BONK · 1h')
    expect(payload?.subtitle).toBe('SOL')
  })

  it('defaults title and subtitle to empty strings when absent or non-string', () => {
    const payload = normalizeChartPayload({ title: 42, candles: [candle(100)] })
    expect(payload?.title).toBe('')
    expect(payload?.subtitle).toBe('')
  })

  it('coerces numeric strings, which is what the GMGN CLI emits', () => {
    const payload = normalizeChartPayload({
      candles: [{ time: '1700000000', open: '1.5', high: '2', low: '1', close: '1.75' }],
    })
    expect(payload?.candles[0]).toEqual({
      time: 1700000000,
      open: 1.5,
      high: 2,
      low: 1,
      close: 1.75,
    })
  })

  it('drops rows missing any OHLC field rather than defaulting them to zero', () => {
    const payload = normalizeChartPayload({
      candles: [candle(100), { time: 200, open: 1, high: 2, low: 1 }, candle(300)],
    })
    expect(payload?.candles.map((c) => c.time)).toEqual([100, 300])
  })

  it('sorts ascending — lightweight-charts asserts on unordered data', () => {
    const payload = normalizeChartPayload({ candles: [candle(300), candle(100), candle(200)] })
    expect(payload?.candles.map((c) => c.time)).toEqual([100, 200, 300])
  })

  it('de-duplicates repeated timestamps, keeping the last restatement', () => {
    const payload = normalizeChartPayload({ candles: [candle(100, 5), candle(100, 9)] })
    expect(payload?.candles).toHaveLength(1)
    expect(payload?.candles[0]?.close).toBe(9)
  })

  it('converts millisecond timestamps to seconds', () => {
    const payload = normalizeChartPayload({ candles: [candle(1754380800000)] })
    expect(payload?.candles[0]?.time).toBe(1754380800)
  })

  it('leaves second-precision timestamps untouched', () => {
    const payload = normalizeChartPayload({ candles: [candle(1754380800)] })
    expect(payload?.candles[0]?.time).toBe(1754380800)
  })

  it('rejects non-positive and non-finite timestamps', () => {
    const payload = normalizeChartPayload({
      candles: [candle(0), candle(-5), { ...candle(1), time: 'soon' }, candle(100)],
    })
    expect(payload?.candles.map((c) => c.time)).toEqual([100])
  })

  it('carries volume when present and drops a negative one', () => {
    const payload = normalizeChartPayload({
      candles: [
        { ...candle(100), volume: 250 },
        { ...candle(200), volume: -3 },
      ],
    })
    expect(payload?.candles[0]?.volume).toBe(250)
    expect(payload?.candles[1]?.volume).toBeUndefined()
  })
})

/* ── hasVolume / volumeSeriesData ───────────────────────────────────────── */

describe('hasVolume', () => {
  it('is true when any candle carries volume', () => {
    const payload = normalizeChartPayload({
      candles: [candle(100), { ...candle(200), volume: 7 }],
    })
    expect(hasVolume(payload!)).toBe(true)
  })
  it('is false when no candle carries volume', () => {
    const payload = normalizeChartPayload({ candles: [candle(100)] })
    expect(hasVolume(payload!)).toBe(false)
  })
})

describe('volumeSeriesData', () => {
  it('colors a rising candle up and a falling candle down, defaulting volume to 0', () => {
    const payload = normalizeChartPayload({
      candles: [
        { time: 100, open: 1, high: 3, low: 1, close: 2, volume: 10 },
        { time: 200, open: 2, high: 3, low: 0.5, close: 1 },
      ],
    })
    const theme = chartTheme('dark')
    const rows = volumeSeriesData(payload!, theme)
    expect(rows[0]).toEqual({ time: 100, value: 10, color: theme.volumeUpColor })
    expect(rows[1]).toEqual({ time: 200, value: 0, color: theme.volumeDownColor })
  })

  it('treats an unchanged close as up, matching the candle body color', () => {
    const payload = normalizeChartPayload({
      candles: [{ time: 100, open: 2, high: 3, low: 1, close: 2, volume: 4 }],
    })
    const theme = chartTheme('light')
    expect(volumeSeriesData(payload!, theme)[0]?.color).toBe(theme.volumeUpColor)
  })
})

/* ── chartTheme ─────────────────────────────────────────────────────────── */

describe('chartTheme', () => {
  it('gives dark and light distinct text colors over a transparent card', () => {
    expect(chartTheme('dark').textColor).not.toBe(chartTheme('light').textColor)
    expect(chartTheme('dark').background).toBe('transparent')
    expect(chartTheme('light').background).toBe('transparent')
  })
})

/* ── priceDecimals ──────────────────────────────────────────────────────── */

describe('priceDecimals', () => {
  const withCloses = (...closes: number[]) =>
    normalizeChartPayload({ candles: closes.map((close, i) => candle((i + 1) * 100, close)) })!

  it('uses 2 decimals for prices at or above 1', () => {
    expect(priceDecimals(withCloses(1, 42, 1500))).toBe(2)
  })

  it('scales past the leading zeros so meme-token moves stay visible', () => {
    // 0.00000123 → 5 leading zeros → 9 decimals, not the default 2.
    expect(priceDecimals(withCloses(0.00000123))).toBe(9)
  })

  it('keys off the smallest close in the range, not the largest', () => {
    // 1e-3 → floor(-log10) = 3 → 3 + 4 = 7, rather than the 2 that 5 alone
    // would have produced.
    expect(priceDecimals(withCloses(5, 0.001))).toBe(7)
  })

  it('ignores zero closes and caps the precision', () => {
    expect(priceDecimals(withCloses(0, 2))).toBe(2)
    expect(priceDecimals(withCloses(1e-30))).toBe(12)
  })
})
