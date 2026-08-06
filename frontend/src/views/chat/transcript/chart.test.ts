// Tests for the chart-artifact renderer (chart.ts).
//
// Two surfaces, mirroring the module: the pure helpers that decide WHAT gets
// drawn (mime matching, payload normalization, the ordering/dedup contract
// lightweight-charts asserts on, the price precision that keeps sub-cent meme
// tokens readable), and the imperative mounter, exercised against a stubbed
// lightweight-charts so a silent "no chart appeared" regression fails here
// rather than only in a live browser. Real canvas painting stays a browser
// concern; everything up to the library call does not.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createArtifactRenderer } from './artifacts'
import {
  CHART_ARTIFACT_MIME,
  chartTheme,
  createChartMounter,
  hasVolume,
  isChartArtifact,
  normalizeChartPayload,
  priceDecimals,
  volumeSeriesData,
} from './chart'

/* ── lightweight-charts stub ────────────────────────────────────────────── */

interface FakeSeries {
  setData: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
}

interface FakeChart {
  addSeries: ReturnType<typeof vi.fn>
  priceScale: ReturnType<typeof vi.fn>
  timeScale: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  remove: ReturnType<typeof vi.fn>
  series: FakeSeries[]
}

const lib = vi.hoisted(() => ({ charts: [] as unknown[], createChart: vi.fn() }))

vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  CandlestickSeries: { kind: 'candlestick' },
  HistogramSeries: { kind: 'histogram' },
  createChart: lib.createChart,
}))

function makeFakeChart(): FakeChart {
  const series: FakeSeries[] = []
  return {
    series,
    addSeries: vi.fn(() => {
      const next: FakeSeries = { setData: vi.fn(), applyOptions: vi.fn() }
      series.push(next)
      return next
    }),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }
}

function createdCharts(): FakeChart[] {
  return lib.charts as FakeChart[]
}

/**
 * The placeholder the artifact renderer emits. The hooks it must carry —
 * `[data-chart-src]` plus the canvas/status/name children — are pinned against
 * the real renderer in artifacts.test.ts; this builds the same shape so the
 * mounter can be exercised on its own.
 */
function placeholder(url: string): HTMLElement {
  const host = document.createElement('div')
  host.className = 'msg-artifact-chart'
  if (url) host.dataset.chartSrc = url
  else host.setAttribute('data-chart-src', '')
  host.innerHTML =
    '<div class="msg-artifact-chart__header">' +
    '<span class="msg-artifact-chart__name">bonk.chart.json</span>' +
    '</div>' +
    '<div class="msg-artifact-chart__canvas"></div>' +
    '<p class="msg-artifact-chart__status">Loading chart…</p>'
  return host
}

function mountRoot(...hosts: HTMLElement[]): HTMLElement {
  const root = document.createElement('div')
  hosts.forEach((host) => root.appendChild(host))
  document.body.appendChild(root)
  return root
}

function statusOf(host: HTMLElement): string {
  return host.querySelector('.msg-artifact-chart__status')?.textContent ?? ''
}

const CANDLES = [
  { time: 100, open: 1, high: 2, low: 1, close: 2, volume: 10 },
  { time: 200, open: 2, high: 3, low: 2, close: 1, volume: 20 },
]

function payloadBody(): unknown {
  return { type: 'candlestick', title: 'BONK · 1h', subtitle: 'SOL · 1h', candles: CANDLES }
}

beforeEach(() => {
  document.body.innerHTML = ''
  lib.charts.length = 0
  lib.createChart.mockReset()
  lib.createChart.mockImplementation(() => {
    const chart = makeFakeChart()
    lib.charts.push(chart)
    return chart
  })
})

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

/* ── createChartMounter ─────────────────────────────────────────────────── */

describe('createChartMounter', () => {
  it('fetches the payload and draws a chart into the placeholder', async () => {
    const fetchPayload = vi.fn(async () => payloadBody())
    const host = placeholder('/api/v1/artifacts/art-1?sessionKey=s&token=t')
    const root = mountRoot(host)
    const mounter = createChartMounter({ fetchPayload, getTheme: () => 'dark' })

    mounter.mountCharts(root)

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))
    expect(fetchPayload).toHaveBeenCalledWith('/api/v1/artifacts/art-1?sessionKey=s&token=t')
    const [chart] = createdCharts()
    // Candles plus the volume histogram, each fed its own data.
    expect(chart?.addSeries).toHaveBeenCalledTimes(2)
    expect(chart?.series[0]?.setData).toHaveBeenCalledWith(
      CANDLES.map((candle) => expect.objectContaining({ time: candle.time, close: candle.close })),
    )
    // The status line is what the user stares at while nothing is painted yet.
    await vi.waitFor(() => expect(statusOf(host)).toBe(''))
  })

  it('titles the card from the payload rather than the artifact filename', async () => {
    const host = placeholder('/api/v1/artifacts/art-1')
    const root = mountRoot(host)
    const mounter = createChartMounter({
      fetchPayload: async () => payloadBody(),
      getTheme: () => 'light',
    })

    mounter.mountCharts(root)

    await vi.waitFor(() =>
      expect(host.querySelector('.msg-artifact-chart__name')?.textContent).toBe('BONK · 1h'),
    )
    // Token metadata is attacker-controlled, so it must never become markup.
    expect(host.querySelector('.msg-artifact-chart__name')?.innerHTML).toBe('BONK · 1h')
  })

  it('mounts a placeholder once even when called after every streamed artifact', async () => {
    const fetchPayload = vi.fn(async () => payloadBody())
    const root = mountRoot(placeholder('/api/v1/artifacts/art-1'))
    const mounter = createChartMounter({ fetchPayload, getTheme: () => 'dark' })

    mounter.mountCharts(root)
    mounter.mountCharts(root)
    mounter.mountCharts(root)

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))
    expect(fetchPayload).toHaveBeenCalledTimes(1)
  })

  it('skips the volume histogram when no candle carries a volume', async () => {
    const root = mountRoot(placeholder('/api/v1/artifacts/art-1'))
    const mounter = createChartMounter({
      fetchPayload: async () => ({ candles: [{ time: 100, open: 1, high: 2, low: 1, close: 2 }] }),
      getTheme: () => 'dark',
    })

    mounter.mountCharts(root)

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))
    expect(createdCharts()[0]?.addSeries).toHaveBeenCalledTimes(1)
  })

  it('says so when the payload cannot be read, instead of leaving "Loading" forever', async () => {
    const host = placeholder('/api/v1/artifacts/art-1')
    const mounter = createChartMounter({
      fetchPayload: async () => ({ candles: [] }),
      getTheme: () => 'dark',
    })

    mounter.mountCharts(mountRoot(host))

    await vi.waitFor(() => expect(statusOf(host)).toBe('Chart data could not be read.'))
    expect(createdCharts()).toHaveLength(0)
  })

  it('says so when the payload request fails', async () => {
    const host = placeholder('/api/v1/artifacts/art-1')
    const mounter = createChartMounter({
      fetchPayload: async () => {
        throw new Error('HTTP 404')
      },
      getTheme: () => 'dark',
    })

    mounter.mountCharts(mountRoot(host))

    await vi.waitFor(() => expect(statusOf(host)).toBe('Chart failed to load.'))
  })

  it('does not fetch for a placeholder that carries no source', async () => {
    const fetchPayload = vi.fn(async () => payloadBody())
    const host = placeholder('')
    const mounter = createChartMounter({ fetchPayload, getTheme: () => 'dark' })

    mounter.mountCharts(mountRoot(host))

    await vi.waitFor(() => expect(statusOf(host)).toBe('Chart data is unavailable.'))
    expect(fetchPayload).not.toHaveBeenCalled()
  })

  it('disposes charts whose row was rebuilt away', async () => {
    // A session switch and "load earlier" both replace every row wholesale.
    const host = placeholder('/api/v1/artifacts/art-1')
    const root = mountRoot(host)
    const mounter = createChartMounter({
      fetchPayload: async () => payloadBody(),
      getTheme: () => 'dark',
    })
    mounter.mountCharts(root)
    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))

    root.innerHTML = ''
    mounter.pruneDetached()

    expect(createdCharts()[0]?.remove).toHaveBeenCalledTimes(1)
  })

  it('re-mounts a rebuilt row rather than treating the old host as still drawn', async () => {
    const root = mountRoot(placeholder('/api/v1/artifacts/art-1'))
    const mounter = createChartMounter({
      fetchPayload: async () => payloadBody(),
      getTheme: () => 'dark',
    })
    mounter.mountCharts(root)
    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))

    root.innerHTML = ''
    root.appendChild(placeholder('/api/v1/artifacts/art-1'))
    mounter.mountCharts(root)

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(2))
    expect(createdCharts()[0]?.remove).toHaveBeenCalledTimes(1)
  })

  it('re-colors live charts on a theme toggle and skips the pruned ones', async () => {
    const first = placeholder('/api/v1/artifacts/art-1')
    const second = placeholder('/api/v1/artifacts/art-2')
    const root = mountRoot(first, second)
    const mounter = createChartMounter({
      fetchPayload: async () => payloadBody(),
      getTheme: () => 'dark',
    })
    mounter.mountCharts(root)
    await vi.waitFor(() => expect(createdCharts()).toHaveLength(2))

    first.remove()
    mounter.applyTheme('light')

    // Re-themed in place, so a toggle does not reset the user's pan/zoom.
    expect(createdCharts()[1]?.applyOptions).toHaveBeenCalled()
    expect(createdCharts()[0]?.applyOptions).not.toHaveBeenCalled()
    expect(createdCharts()[0]?.remove).toHaveBeenCalledTimes(1)
  })

  it('drops a chart whose row disappeared while the payload was in flight', async () => {
    const host = placeholder('/api/v1/artifacts/art-1')
    const root = mountRoot(host)
    let release = (): void => {}
    const mounter = createChartMounter({
      fetchPayload: async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return payloadBody()
      },
      getTheme: () => 'dark',
    })

    mounter.mountCharts(root)
    root.innerHTML = ''
    release()

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))
    await vi.waitFor(() => expect(createdCharts()[0]?.remove).toHaveBeenCalledTimes(1))
  })

  it('tears every chart down on route unmount', async () => {
    const root = mountRoot(
      placeholder('/api/v1/artifacts/art-1'),
      placeholder('/api/v1/artifacts/art-2'),
    )
    const mounter = createChartMounter({
      fetchPayload: async () => payloadBody(),
      getTheme: () => 'dark',
    })
    mounter.mountCharts(root)
    await vi.waitFor(() => expect(createdCharts()).toHaveLength(2))

    mounter.destroyAll()

    expect(createdCharts()[0]?.remove).toHaveBeenCalledTimes(1)
    expect(createdCharts()[1]?.remove).toHaveBeenCalledTimes(1)
  })
})

/* ── renderer → mounter contract ────────────────────────────────────────── */

describe('the artifact renderer and the chart mounter agree on the placeholder', () => {
  it('draws a chart into markup produced by the real artifact renderer', async () => {
    // The two modules meet through class names and a data attribute only, so
    // nothing but a test like this catches a rename on one side.
    const bubble = document.createElement('div')
    const body = document.createElement('div')
    body.className = 'msg-body'
    bubble.appendChild(body)
    document.body.appendChild(bubble)

    const renderer = createArtifactRenderer({
      ensureStreamBubble: () => bubble,
      markVisibleStreamEvent: () => {},
      scrollToBottom: () => {},
      getAutoScroll: () => false,
      getStreamBubble: () => bubble,
      pushStreamArtifact: () => {},
      getStreamArtifacts: () => [],
      getSessionKey: () => 'agent:main:webchat:test',
      getAuthToken: () => 'tok',
      esc: (value) => value,
    })
    body.innerHTML = renderer.renderArtifacts([
      {
        id: 'art-1',
        name: 'bonk.chart.json',
        mime: CHART_ARTIFACT_MIME,
        download_url: '/api/v1/artifacts/art-1',
      },
    ])

    const fetchPayload = vi.fn(async () => payloadBody())
    createChartMounter({ fetchPayload, getTheme: () => 'dark' }).mountCharts(body)

    await vi.waitFor(() => expect(createdCharts()).toHaveLength(1))
    expect(fetchPayload).toHaveBeenCalledWith(
      '/api/v1/artifacts/art-1?sessionKey=agent%3Amain%3Awebchat%3Atest&token=tok',
    )
    expect(body.querySelector('.msg-artifact-chart__status')?.textContent).toBe('')
  })
})
