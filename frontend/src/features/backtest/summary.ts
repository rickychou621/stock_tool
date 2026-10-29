import type { StockPerformance } from './types'

export function summarizeRule(stocks: StockPerformance[], ruleId: number) {
  const matching = stocks.filter((stock) => stock.ruleId === ruleId)
  const signalStockCount = matching.filter((stock) => stock.metrics.tradeCount > 0).length
  const tradeCount = matching.reduce((total, stock) => total + stock.metrics.tradeCount, 0)
  const sampleSufficient = tradeCount >= 30 && signalStockCount >= 10
  const winRates = matching
    .filter((stock) => stock.metrics.tradeCount > 0)
    .map((stock) => stock.metrics.winRate)
    .filter((rate): rate is number => rate !== null)
    .sort((a, b) => a - b)
  const middle = Math.floor(winRates.length / 2)
  const medianWinRate = !sampleSufficient || !winRates.length ? null : winRates.length % 2
    ? winRates[middle]
    : (winRates[middle - 1] + winRates[middle]) / 2

  return {
    stockCount: matching.length,
    signalStockCount,
    tradeCount,
    sampleSufficient,
    beatBenchmarkCount: matching.filter((stock) =>
      stock.metrics.compoundReturn !== null && stock.benchmarkBuyHoldReturn !== null &&
      stock.metrics.compoundReturn > stock.benchmarkBuyHoldReturn,
    ).length,
    medianWinRate,
  }
}
