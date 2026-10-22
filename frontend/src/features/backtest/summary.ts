import type { StockPerformance } from './types'

export function summarizeRule(stocks: StockPerformance[], ruleId: number) {
  const matching = stocks.filter((stock) => stock.ruleId === ruleId)
  const winRates = matching
    .filter((stock) => stock.metrics.tradeCount > 0)
    .map((stock) => stock.metrics.winRate)
    .filter((rate): rate is number => rate !== null)
    .sort((a, b) => a - b)
  const middle = Math.floor(winRates.length / 2)
  const medianWinRate = !winRates.length ? null : winRates.length % 2
    ? winRates[middle]
    : (winRates[middle - 1] + winRates[middle]) / 2

  return {
    stockCount: matching.length,
    beatBenchmarkCount: matching.filter((stock) =>
      stock.metrics.compoundReturn !== null && stock.benchmarkBuyHoldReturn !== null &&
      stock.metrics.compoundReturn > stock.benchmarkBuyHoldReturn,
    ).length,
    medianWinRate,
  }
}
