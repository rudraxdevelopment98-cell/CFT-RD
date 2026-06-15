"""Risk controls. This is the part that keeps a bug or a bad streak from
emptying the account. Tune in config, never bypass."""
from datetime import date


class RiskManager:
    def __init__(self, per_trade_pct=0.02, daily_loss_limit_pct=0.05,
                 max_open=3):
        self.per_trade_pct = per_trade_pct          # stake per trade vs equity
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_open = max_open
        self.day_start_equity = None
        self.halted = False
        self.day = None

    def new_day(self, equity):
        self.day_start_equity = equity
        self.halted = False
        self.day = date.today()

    def maybe_new_day(self, equity):
        """Reset the daily limit when the calendar day rolls over.

        Lets a long-running live loop re-arm itself each day without an
        external scheduler. Returns True if a new day was started.
        """
        if self.day != date.today():
            self.new_day(equity)
            return True
        return False

    def check_daily_limit(self, equity):
        """Trip the kill switch if today's drawdown breaches the limit."""
        if self.day_start_equity is None:
            self.day_start_equity = equity
        dd = equity / self.day_start_equity - 1
        if dd <= -self.daily_loss_limit_pct:
            self.halted = True
        return not self.halted

    def can_open(self, open_positions):
        return not self.halted and open_positions < self.max_open

    def stake(self, equity):
        """Cash/notional to allocate to one new position."""
        return equity * self.per_trade_pct
