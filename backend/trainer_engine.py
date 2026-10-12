# -*- coding: utf-8 -*-
"""Training engine — K-line step-through, order matching, PnL settlement."""


class Order:
    def __init__(self, side, qty, entry_price, entry_idx, stop_loss=None, take_profit=None):
        self.side = side            # 'long' | 'short'
        self.qty = qty
        self.entry_price = entry_price
        self.entry_idx = entry_idx
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.exit_price = None
        self.exit_idx = None
        self.pnl = 0.0
        self.commission = 0.0
        self.status = 'open'        # 'open' | 'closed' | 'cancelled'

    def unrealized_pnl(self, current_price):
        if self.side == 'long':
            return (current_price - self.entry_price) * self.qty
        else:
            return (self.entry_price - current_price) * self.qty


class TrainingEngine:
    def __init__(self, bars, config=None):
        self._bars = bars                        # list of dicts (date, open, high, low, close, volume)
        self.cursor = 0
        self._config = config or {}
        self.initial_balance = self._config.get('initial_balance', 100000.0)
        self.commission_rate = self._config.get('commission_rate', 0.0003)  # default 0.03%
        self.min_qty = self._config.get('min_qty', 100)
        self.allow_short = self._config.get('allow_short', True)
        self.balance = self.initial_balance
        self.orders = []               # active orders
        self.closed_orders = []        # history

    @property
    def total_bars(self):
        return len(self._bars)

    @property
    def progress(self):
        return self.cursor / max(self.total_bars - 1, 1)

    @property
    def is_last(self):
        return self.cursor >= self.total_bars - 1

    @property
    def is_first(self):
        return self.cursor <= 0

    def current_bar(self):
        if 0 <= self.cursor < self.total_bars:
            return self._bars[self.cursor]
        return None

    def bar_at(self, idx):
        if 0 <= idx < self.total_bars:
            return self._bars[idx]
        return None

    def step(self):
        if self.is_last:
            return False
        self.cursor += 1
        bar = self.current_bar()
        self._check_orders(bar)
        return True

    def step_back(self):
        if self.is_first:
            return False
        self.cursor -= 1
        return True

    def goto(self, idx):
        if 0 <= idx < self.total_bars:
            self.cursor = idx

    def place_order(self, side, qty, stop_loss=None, take_profit=None):
        bar = self.current_bar()
        if bar is None or qty <= 0:
            return None
        qty = (qty // self.min_qty) * self.min_qty
        if qty <= 0:
            return None

        order = Order(
            side=side,
            qty=qty,
            entry_price=bar['close'],
            entry_idx=self.cursor,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        order.commission = order.entry_price * order.qty * self.commission_rate
        self.balance -= order.commission
        self.orders.append(order)
        return order

    def cancel_order(self, order):
        if order in self.orders:
            self.balance += order.commission
            order.commission = 0.0
            order.status = 'cancelled'
            self.orders.remove(order)
            self.closed_orders.append(order)

    def _check_orders(self, bar):
        triggered = []
        for order in self.orders:
            if self._is_triggered(order, bar):
                triggered.append(order)
        for order in triggered:
            self._settle(order, bar)

    def _is_triggered(self, order, bar):
        if order.stop_loss is not None:
            if order.side == 'long' and bar['low'] <= order.stop_loss:
                return True
            if order.side == 'short' and bar['high'] >= order.stop_loss:
                return True
        if order.take_profit is not None:
            if order.side == 'long' and bar['high'] >= order.take_profit:
                return True
            if order.side == 'short' and bar['low'] <= order.take_profit:
                return True
        return False

    def _settle(self, order, bar):
        if order.stop_loss is not None and (
            (order.side == 'long' and bar['low'] <= order.stop_loss) or
            (order.side == 'short' and bar['high'] >= order.stop_loss)
        ):
            exit_price = order.stop_loss
        elif order.take_profit is not None and (
            (order.side == 'long' and bar['high'] >= order.take_profit) or
            (order.side == 'short' and bar['low'] <= order.take_profit)
        ):
            exit_price = order.take_profit
        else:
            exit_price = bar['close']

        order.exit_price = exit_price
        order.exit_idx = self.cursor

        if order.side == 'long':
            order.pnl = (exit_price - order.entry_price) * order.qty
        else:
            order.pnl = (order.entry_price - exit_price) * order.qty

        exit_commission = exit_price * order.qty * self.commission_rate
        order.commission += exit_commission
        order.pnl -= exit_commission
        order.status = 'closed'

        self.balance += exit_price * order.qty
        if order.side == 'long':
            self.balance -= order.entry_price * order.qty
        else:
            self.balance -= order.entry_price * order.qty
        self.balance -= exit_commission

        self.orders.remove(order)
        self.closed_orders.append(order)

    def floating_pnl(self):
        bar = self.current_bar()
        if bar is None:
            return 0.0
        total = 0.0
        for order in self.orders:
            total += order.unrealized_pnl(bar['close'])
        return total

    def total_equity(self):
        return self.balance + self.floating_pnl()

    def total_realized_pnl(self):
        return sum(o.pnl for o in self.closed_orders)

    def win_rate(self):
        closed = [o for o in self.closed_orders if o.status == 'closed']
        if not closed:
            return 0.0
        wins = sum(1 for o in closed if o.pnl > 0)
        return wins / len(closed)

    def snapshot(self):
        bar = self.current_bar()
        return {
            'cursor': self.cursor,
            'total_bars': self.total_bars,
            'progress': self.progress,
            'balance': self.balance,
            'floating_pnl': self.floating_pnl(),
            'total_equity': self.total_equity(),
            'realized_pnl': self.total_realized_pnl(),
            'win_rate': self.win_rate(),
            'open_orders': len(self.orders),
            'closed_orders': len(self.closed_orders),
            'current_price': bar['close'] if bar else 0,
            'current_date': bar['date'] if bar else '',
        }
