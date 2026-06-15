"""PaperBroker is the truth-teller before live — fees, slippage, accounting."""
from bot.brokers import PaperBroker


def test_buy_then_close_at_higher_price_is_profitable():
    b = PaperBroker(cash=10_000, fee=0.001, slip=0.0005)
    b.buy("BTC/USDT", stake=1_000, price=100)
    assert b.cash == 9_000
    assert b.open_count() == 1
    res = b.close("BTC/USDT", price=110)               # +10% gross, minus costs
    assert 0.08 < res["pnl_pct"] < 0.10                 # still clearly positive
    assert b.open_count() == 0
    assert b.closed[-1] == res["pnl_pct"]


def test_slippage_and_fee_make_a_flat_round_trip_a_small_loss():
    b = PaperBroker(cash=10_000)
    b.buy("X", stake=1_000, price=100)
    res = b.close("X", price=100)
    assert res["pnl_pct"] < 0                           # costs eat a flat trade


def test_buy_is_capped_at_available_cash():
    b = PaperBroker(cash=500)
    b.buy("X", stake=1_000, price=100)
    assert b.cash == 0                                  # stake clipped to 500


def test_close_unknown_symbol_returns_none():
    assert PaperBroker().close("NOPE", 100) is None


def test_equity_marks_open_positions_to_market():
    b = PaperBroker(cash=10_000)
    b.buy("X", stake=1_000, price=100)
    assert b.equity({"X": 200}) > b.equity({"X": 100})  # mark-up raises equity
