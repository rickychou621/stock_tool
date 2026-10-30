// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StockChart } from './StockChart'

const mock = vi.hoisted(() => {
  const series = () => ({
    setData: vi.fn(), applyOptions: vi.fn(), createPriceLine: vi.fn(() => ({})), removePriceLine: vi.fn(),
  })
  const candles = series()
  const chart = {
    addSeries: vi.fn((kind: string) => kind === 'candle' ? candles : series()),
    panes: () => [], timeScale: () => ({ fitContent: vi.fn() }),
    subscribeCrosshairMove: vi.fn(), unsubscribeCrosshairMove: vi.fn(), remove: vi.fn(),
  }
  return { candles, chart, createChart: vi.fn(() => chart), setMarkers: vi.fn() }
})
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candle', LineSeries: 'line', HistogramSeries: 'histogram',
  LineStyle: { Dotted: 1, Dashed: 2 }, createChart: mock.createChart,
  createSeriesMarkers: () => ({ setMarkers: mock.setMarkers }),
}))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })
const bars = ['2026-10-22', '2026-10-23'].map((date) => ({
  date, open: 100, high: 102, low: 99, close: 101, volume: 1000,
}))
const props = {
  bars, emaVisibility: { ema10: true, ma20: true, ema60: true },
  bollingerVisible: true, subPanelIndicator: 'kd' as const,
}
function browserMocks() {
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
}
it('更新觸價與歷史標記不重建圖表，排除範圍外、其他狀態及同日重複標記', () => {
  browserMocks()
  const view = render(<StockChart {...props} priceLines={[{ price: 98, title: '', ruleName: '戰法二', color: '#991b1b' }]} />)
  expect(mock.chart.addSeries).toHaveBeenCalledWith('candle', expect.objectContaining({
    lastValueVisible: false, priceLineVisible: false,
  }))
  expect(mock.candles.createPriceLine).toHaveBeenCalledWith(expect.objectContaining({
    axisLabelVisible: false, price: 101,
  }))
  expect(mock.candles.createPriceLine).toHaveBeenCalledWith(expect.objectContaining({
    axisLabelVisible: false, price: 98,
  }))
  expect(screen.getByLabelText('價格線圖例').textContent).toBe('┈ 現價 101.00— 戰法二 觸價 98.00')
  const oldLine = mock.candles.createPriceLine.mock.results[0].value
  view.rerender(<StockChart {...props} priceLines={[]} markers={[
    { date: '2026-10-23', state: 'EXIT', ruleName: '二' },
    { date: '2026-10-22', state: 'HOLD', ruleName: '一' },
    { date: '2026-10-22', state: 'ENTRY', ruleName: '一' },
    { date: '2026-10-22', state: 'EXIT', ruleName: '二' },
    { date: '2026-10-21', state: 'ENTRY', ruleName: '一' },
  ]} />)
  expect(mock.createChart).toHaveBeenCalledTimes(1)
  expect(mock.candles.removePriceLine).toHaveBeenCalledWith(oldLine)
  expect(mock.setMarkers).toHaveBeenLastCalledWith([
    { time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', color: '#d03b3b', text: '進' },
    { time: '2026-10-23', position: 'aboveBar', shape: 'arrowDown', color: '#0ca30c', text: '出' },
  ])
})
it('OHLC 與副圖顯示游標日期，離開後恢復最新日期', () => {
  browserMocks()
  const view = render(<StockChart {...props} />)
  expect(screen.getAllByText('2026/10/23（最新）')).toHaveLength(2)
  const move = mock.chart.subscribeCrosshairMove.mock.calls[0][0]
  act(() => move({ time: { year: 2026, month: 10, day: 22 }, seriesData: new Map([
    [mock.candles, { time: { year: 2026, month: 10, day: 22 }, ...bars[0] }],
  ]) }))
  expect(screen.getAllByText('2026/10/22')).toHaveLength(2)
  view.rerender(<StockChart {...props} subPanelIndicator="macd" />)
  expect(screen.getAllByText('2026/10/22')).toHaveLength(2)
  act(() => move({ time: undefined, seriesData: new Map() }))
  expect(screen.getAllByText('2026/10/23（最新）')).toHaveLength(2)
})

it('月線使用 20SMA 並移除重複的布林中軌', () => {
  browserMocks()
  const history = Array.from({ length: 21 }, (_, index) => ({
    ...bars[0], date: `2026-10-${String(index + 1).padStart(2, '0')}`, close: index + 1,
  }))
  render(<StockChart {...props} bars={history} />)
  const calls = mock.chart.addSeries.mock.calls as unknown as [string, { color: string }][]
  const monthly = calls.findIndex(([, options]) => options.color === '#eb6834')
  expect(mock.chart.addSeries.mock.results[monthly].value.setData).toHaveBeenCalledWith([
    { time: '2026-10-20', value: 10.5 }, { time: '2026-10-21', value: 11.5 },
  ])
  expect(calls.some(([, options]) => options.color === '#1baf7a')).toBe(false)
  expect(calls.filter(([, options]) => options.color === '#e87ba4')).toHaveLength(2)
})
