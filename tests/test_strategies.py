"""The strategies decide when money moves — pin their signals down."""
import numpy as np

from bot.strategies import ema, rsi, trend, meanrev, breakout, REGISTRY
from conftest import ohlcv


def _scan_for_signal(closes, strat, want, warmup=210, **kw):
    """Replay a price path bar by bar; return the first window where `strat`
    emits `want` (mirrors how the live engine calls strategies)."""
    df = ohlcv(closes, **kw)
    for i in range(warmup, len(df)):
        sig, _ = strat(df.iloc[: i + 1])
        if sig == want:
            return df.iloc[: i + 1]
    return None


def test_registry_has_three_strategies():
    assert set(REGISTRY) == {"trend", "meanrev", "breakout"}


def test_ema_orders_fast_above_slow_in_an_uptrend():
    s = ohlcv(np.linspace(100, 200, 300)).close
    assert ema(s, 20).iloc[-1] > ema(s, 200).iloc[-1]


def test_rsi_is_bounded_and_reads_overbought_after_a_rally():
    # down-leg first (so avg-loss > 0), then a sustained rally -> high RSI.
    closes = list(range(100, 80, -1)) + list(range(80, 140))
    r = rsi(ohlcv(closes).close, 14)
    assert (r >= 0).all() and (r <= 100).all()
    assert r.iloc[-1] > 70


def test_trend_enters_on_golden_cross_above_200ema():
    # Established uptrend (price well above the lagging 200-EMA), a shallow
    # pullback that crosses 20-EMA below 50-EMA, then a resumption that crosses
    # back up — a golden cross while still above the 200-EMA regime filter.
    closes = np.concatenate([
        np.linspace(100, 300, 250),     # long uptrend -> 200-EMA lags far below
        np.linspace(300, 280, 30),      # shallow pullback -> fast dips under slow
        np.linspace(280, 360, 60),      # resumption -> golden cross back up
    ])
    assert _scan_for_signal(closes, trend, "enter") is not None


def test_trend_exits_on_death_cross():
    closes = np.concatenate([np.linspace(100, 300, 250), np.linspace(300, 120, 120)])
    assert _scan_for_signal(closes, trend, "exit") is not None


def test_meanrev_enters_crossing_up_out_of_oversold():
    # drop hard (RSI below 30), then a single up bar to cross back above 30.
    closes = list(np.linspace(200, 120, 40)) + [121, 135]
    sig, stop = meanrev(ohlcv(closes))
    assert sig == "enter" and stop == 0.05


def test_meanrev_carries_stop_even_when_flat():
    sig, stop = meanrev(ohlcv(np.linspace(100, 101, 50)))
    assert stop == 0.05                                # 5% hard stop always present


def test_breakout_needs_new_high_and_volume():
    closes = list(np.full(30, 100.0)) + [130.0]        # break above prior 20-high
    vol = list(np.full(30, 100.0)) + [500.0]           # with a volume surge
    sig, _ = breakout(ohlcv(closes, volume=vol))
    assert sig == "enter"
    # same breakout but no volume confirmation -> no entry
    vol_flat = list(np.full(30, 100.0)) + [10.0]
    sig2, _ = breakout(ohlcv(closes, volume=vol_flat))
    assert sig2 != "enter"
