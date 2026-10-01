"""條件庫共用的技術指標計算，純函式、不碰資料庫，方便單獨測試。"""

from app.conditions.types import ConditionBar


def calculate_ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    smoothing = 2 / (period + 1)
    ema = [values[0]]
    for value in values[1:]:
        ema.append(value * smoothing + ema[-1] * (1 - smoothing))
    return ema


def calculate_sma(values: list[float], period: int) -> list[float | None]:
    """回傳跟values等長的簡單移動平均，前(period-1)筆資料不足時為None。"""
    result: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
            continue
        window = values[i - period + 1 : i + 1]
        result.append(sum(window) / period)
    return result


def calculate_bollinger_bands(
    values: list[float], period: int = 20, num_std: float = 2.0
) -> list[tuple[float, float, float] | None]:
    """回傳跟values等長的(上軌, 中軌, 下軌)序列，前(period-1)筆資料不足時為None。
    中軌=period日SMA，上下軌=中軌 ± num_std倍母體標準差。"""
    result: list[tuple[float, float, float] | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
            continue
        window = values[i - period + 1 : i + 1]
        mid = sum(window) / period
        variance = sum((v - mid) ** 2 for v in window) / period
        std = variance**0.5
        result.append((mid + num_std * std, mid, mid - num_std * std))
    return result


def calculate_kd(bars: list[ConditionBar], period: int = 9) -> list[tuple[float, float]]:
    """標準KD(隨機指標)：RSV為n期內的相對位置，K/D各自用2/3前值+1/3新值平滑。"""
    result: list[tuple[float, float]] = []
    prev_k, prev_d = 50.0, 50.0

    for i in range(len(bars)):
        window = bars[max(0, i - period + 1) : i + 1]
        highest = max(b.high for b in window)
        lowest = min(b.low for b in window)
        rsv = 50.0 if highest == lowest else (bars[i].close - lowest) / (highest - lowest) * 100

        k = (prev_k * 2 + rsv) / 3
        d = (prev_d * 2 + k) / 3
        prev_k, prev_d = k, d
        result.append((k, d))

    return result


def calculate_macd(
    values: list[float], short_period: int = 12, long_period: int = 26, signal_period: int = 9
) -> list[tuple[float, float]]:
    """回傳(DIF, MACD訊號線)序列。DIF=短EMA-長EMA，MACD訊號線=DIF的EMA。"""
    ema_short = calculate_ema(values, short_period)
    ema_long = calculate_ema(values, long_period)
    dif = [s - long_val for s, long_val in zip(ema_short, ema_long, strict=True)]
    macd_signal = calculate_ema(dif, signal_period)
    return list(zip(dif, macd_signal, strict=True))


def resample_to_monthly(bars: list[ConditionBar]) -> list[ConditionBar]:
    """把日K依(年,月)分組合併成月K：開=當月第一筆開盤、高=當月最高、低=當月最低、
    收=當月最後一筆收盤、量=當月總量。假設bars已依日期升冪排序。"""
    monthly: list[ConditionBar] = []
    current_key: tuple[int, int] | None = None
    group: list[ConditionBar] = []

    def flush() -> None:
        if not group:
            return
        monthly.append(
            ConditionBar(
                trade_date=group[-1].trade_date,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )

    for bar in bars:
        key = (bar.trade_date.year, bar.trade_date.month)
        if key != current_key:
            flush()
            group = []
            current_key = key
        group.append(bar)
    flush()

    return monthly
