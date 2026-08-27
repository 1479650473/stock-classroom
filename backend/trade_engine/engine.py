# -*- coding: utf-8 -*-
"""TradeEngine — simulated account, order matching, position settlement."""

import sqlite3
from datetime import date

from .schema import ensure_tables, get_db_path
from .models import make_account, make_order, make_position, make_trade


class TradeEngine:
    COMMISSION_RATE = 0.0003
    STAMP_TAX_RATE = 0.0005
    POSITION_LIMIT = 0.30
    LOT_SIZE = 100

    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        ensure_tables(self.db_path)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ═══════════════════════════════════════════════════════════════
    #  Account
    # ═══════════════════════════════════════════════════════════════

    def create_account(self, name, initial_capital=100000):
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO accounts (name, initial_capital, balance) VALUES (?, ?, ?)",
            (name, initial_capital, initial_capital),
        )
        conn.commit()
        aid = cur.lastrowid
        conn.close()
        return aid

    def rename_account(self, account_id, name):
        conn = self._conn()
        conn.execute("UPDATE accounts SET name=? WHERE id=?", (name, account_id))
        conn.commit()
        conn.close()

    def get_account(self, account_id):
        conn = self._conn()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        conn.close()
        return make_account(row) if row else None

    def list_accounts(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM accounts WHERE is_active=1 ORDER BY id").fetchall()
        conn.close()
        return [make_account(r) for r in rows]

    def list_account_summaries(self):
        """所有账户 + 各自完整摘要(余额/市值/总资产/盈亏/持仓数). 供账户中心/总览复用."""
        out = []
        for a in self.list_accounts():
            s = self.get_summary(a['id'])
            if s:
                out.append(s)
        return out

    def delete_account(self, account_id):
        conn = self._conn()
        conn.execute("DELETE FROM orders WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM positions WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM trades WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        conn.commit()
        conn.close()

    def reset_account(self, account_id):
        acc = self.get_account(account_id)
        if acc is None:
            return
        conn = self._conn()
        conn.execute("DELETE FROM orders WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM positions WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM trades WHERE account_id=?", (account_id,))
        conn.execute(
            "UPDATE accounts SET balance=?, frozen=?, total_profit=? WHERE id=?",
            (acc['initial_capital'], 0, 0, account_id),
        )
        conn.commit()
        conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  Order
    # ═══════════════════════════════════════════════════════════════

    def place_order(self, account_id, code, name, side, order_type,
                    price, qty, current_price=None, trade_date=None):
        side = side.lower().strip()
        order_type = order_type.lower().strip()

        if side not in ('buy', 'sell'):
            return None, "方向错误，必须是 buy 或 sell"
        if order_type not in ('market', 'limit'):
            return None, "订单类型错误，必须是 market 或 limit"
        if qty < self.LOT_SIZE:
            return None, f"数量不能少于 {self.LOT_SIZE} 股"
        qty = (qty // self.LOT_SIZE) * self.LOT_SIZE

        if order_type == 'market':
            if current_price is None or current_price <= 0:
                return None, "市价单需要提供当前价 current_price"
            exec_price = current_price
        else:
            if price <= 0:
                return None, "限价单必须指定有效价格"
            exec_price = price

        if trade_date is None:
            trade_date = date.today().isoformat()

        conn = self._conn()
        try:
            acc = make_account(conn.execute(
                "SELECT * FROM accounts WHERE id=? AND is_active=1",
                (account_id,)).fetchone())
            if acc is None:
                return None, "账户不存在或已停用"

            if side == 'buy':
                err = self._validate_buy(conn, acc, code, exec_price, qty)
                if err:
                    return None, err
            else:
                err = self._validate_sell(conn, acc, code, exec_price, qty, trade_date)
                if err:
                    return None, err

            if order_type == 'market':
                order, trade = self._execute_market(conn, acc, code, name, side,
                                                    exec_price, qty, trade_date)
            else:
                order = self._save_pending(conn, acc, code, name, side, price, qty)
                conn.commit()
                return order, None

            conn.commit()
            return order, trade
        except Exception as e:
            conn.rollback()
            return None, str(e)
        finally:
            conn.close()

    def cancel_order(self, order_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if row is None:
                return False, "订单不存在"
            order = make_order(row)
            if order['status'] not in ('pending', 'partial'):
                return False, "只能撤销待成交的订单"

            if order['side'] == 'buy':
                cost = order['price'] * order['qty'] * (1 + self.COMMISSION_RATE)
                conn.execute(
                    "UPDATE accounts SET frozen=frozen-?, balance=balance+? WHERE id=?",
                    (cost, cost, order['account_id']),
                )
            else:
                conn.execute(
                    "UPDATE positions SET frozen_qty=frozen_qty-? WHERE account_id=? AND code=?",
                    (order['qty'] - order['filled_qty'], order['account_id'], order['code']),
                )

            conn.execute(
                "UPDATE orders SET status='cancelled',"
                " updated_at=datetime('now','localtime') WHERE id=?",
                (order_id,),
            )
            conn.commit()
            return True, None
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  Matching — check pending limit orders against latest price
    # ═══════════════════════════════════════════════════════════════

    def check_orders(self, account_id, code, current_price, trade_date=None):
        if trade_date is None:
            trade_date = date.today().isoformat()

        conn = self._conn()
        trades = []
        try:
            rows = conn.execute(
                """SELECT * FROM orders
                   WHERE account_id=? AND code=? AND order_type='limit'
                     AND status='pending'
                   ORDER BY created_at""",
                (account_id, code),
            ).fetchall()

            for row in rows:
                order = make_order(row)
                should_fill = (
                    (order['side'] == 'buy' and current_price <= order['price']) or
                    (order['side'] == 'sell' and current_price >= order['price'])
                )
                if not should_fill:
                    continue

                acc = make_account(conn.execute(
                    "SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())

                order, trade = self._execute_limit(conn, acc, order, trade_date)
                if trade:
                    trades.append(trade)
                else:
                    break

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
        return trades

    # ═══════════════════════════════════════════════════════════════
    #  Position
    # ═══════════════════════════════════════════════════════════════

    def get_positions(self, account_id):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM positions WHERE account_id=? AND qty>0 ORDER BY code",
            (account_id,),
        ).fetchall()
        conn.close()
        return [make_position(r) for r in rows]

    def update_position_price(self, account_id, code, price):
        conn = self._conn()
        conn.execute(
            """UPDATE positions SET current_price=?, market_value=qty*?,
               float_pnl=qty*(?-cost_price)
               WHERE account_id=? AND code=? AND qty>0""",
            (price, price, price, account_id, code),
        )
        conn.commit()
        conn.close()

    def update_all_prices(self, account_id, code_prices):
        """batch update: code_prices = {code: price}"""
        conn = self._conn()
        for code, price in code_prices.items():
            conn.execute(
                """UPDATE positions SET current_price=?, market_value=qty*?,
                   float_pnl=qty*(?-cost_price)
                   WHERE account_id=? AND code=? AND qty>0""",
                (price, price, price, account_id, code),
            )
        conn.commit()
        conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  Trade history
    # ═══════════════════════════════════════════════════════════════

    def get_trades(self, account_id, limit=50):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM trades WHERE account_id=? ORDER BY id DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
        conn.close()
        return [make_trade(r) for r in rows]

    def get_orders(self, account_id, status=None, limit=50):
        conn = self._conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM orders WHERE account_id=? AND status=?"
                " ORDER BY id DESC LIMIT ?",
                (account_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders WHERE account_id=? ORDER BY id DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        conn.close()
        return [make_order(r) for r in rows]

    # ═══════════════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════════════

    def get_summary(self, account_id):
        acc = self.get_account(account_id)
        if acc is None:
            return None

        positions = self.get_positions(account_id)
        total_mv = sum(p['market_value'] for p in positions)
        total_fp = sum(p['float_pnl'] for p in positions)
        total_assets = acc['balance'] + acc['frozen'] + total_mv
        total_profit = total_assets - acc['initial_capital']

        return {
            'account_id': account_id,
            'name': acc['name'],
            'initial_capital': acc['initial_capital'],
            'balance': acc['balance'],
            'frozen': acc['frozen'],
            'market_value': total_mv,
            'float_pnl': total_fp,
            'total_assets': total_assets,
            'total_profit': total_profit,
            'total_profit_pct': (
                total_profit / acc['initial_capital'] * 100
                if acc['initial_capital'] else 0
            ),
            'positions': len(positions),
            'pending_orders': len(self.get_orders(account_id, 'pending')),
            'total_trades': len(self.get_trades(account_id)),
        }

    def snapshot_nav(self, account_id, date=None):
        """记录账户当日净值快照(幂等: 同日覆盖). 供每日收盘/操盘后调用, 累计真实净值曲线."""
        from datetime import datetime
        s = self.get_summary(account_id)
        if s is None:
            return None
        day = date or datetime.now().strftime("%Y-%m-%d")
        initial = float(s['initial_capital']) or 1.0
        conn = self._conn()
        conn.execute(
            "INSERT INTO account_nav (account_id, date, nav, total_assets, balance, market_value) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(account_id, date) DO UPDATE SET nav=excluded.nav, total_assets=excluded.total_assets, "
            "balance=excluded.balance, market_value=excluded.market_value",
            (account_id, day, round(s['total_assets'] / initial, 5),
             s['total_assets'], s['balance'], s['market_value']))
        conn.commit()
        conn.close()
        return {"date": day, "nav": round(s['total_assets'] / initial, 5)}

    def get_nav_history(self, account_id):
        """已记录的每日净值曲线(真实快照, 升序). 无快照→空(由总览提示'尚未记录', 不伪造历史).

        Returns {dates: [YYYY-MM-DD], nav: [倍数], total_assets: [float]}. """
        conn = self._conn()
        rows = conn.execute(
            "SELECT date, nav, total_assets FROM account_nav WHERE account_id=? ORDER BY date",
            (account_id,)).fetchall()
        conn.close()
        if not rows:
            return {"dates": [], "nav": [], "total_assets": []}
        return {"dates": [r[0] for r in rows], "nav": [float(r[1]) for r in rows],
                "total_assets": [float(r[2]) for r in rows]}

    # ═══════════════════════════════════════════════════════════════
    #  Internal: validation
    # ═══════════════════════════════════════════════════════════════

    def _validate_buy(self, conn, acc, code, price, qty):
        cost = price * qty * (1 + self.COMMISSION_RATE)
        if acc['balance'] < cost:
            return f"可用资金不足，需要 {cost:,.2f}，余额 {acc['balance']:,.2f}"

        pos_rows = conn.execute(
            "SELECT * FROM positions WHERE account_id=? AND qty>0",
            (acc['id'],),
        ).fetchall()
        total_holdings = sum(p['qty'] * p['cost_price'] for p in pos_rows)
        existing = conn.execute(
            "SELECT * FROM positions WHERE account_id=? AND code=?",
            (acc['id'], code),
        ).fetchone()
        after_buy = price * qty
        if existing:
            after_buy += existing['qty'] * existing['cost_price']
        total = acc['balance'] + acc['frozen'] + total_holdings
        ratio = after_buy / (total + price * qty) if total > 0 else 1
        if ratio > self.POSITION_LIMIT:
            return (f"单票仓位不得超过 {self.POSITION_LIMIT*100:.0f}%，"
                    f"当前该股占比将达到 {ratio*100:.1f}%")
        return None

    def _validate_sell(self, conn, acc, code, price, qty, trade_date):
        pos = conn.execute(
            "SELECT * FROM positions WHERE account_id=? AND code=?",
            (acc['id'], code),
        ).fetchone()
        if pos is None or pos['qty'] <= 0:
            return "没有该股票的持仓"
        available = pos['qty'] - pos['frozen_qty']
        if available < qty:
            return f"可卖数量不足，持仓 {pos['qty']}股，冻结 {pos['frozen_qty']}股"
        if pos['last_buy_date'] and pos['last_buy_date'] == trade_date:
            return "今日买入的股票需T+1日才能卖出"
        return None

    # ═══════════════════════════════════════════════════════════════
    #  Internal: execution
    # ═══════════════════════════════════════════════════════════════

    def _execute_market(self, conn, acc, code, name, side,
                        price, qty, trade_date):
        commission = price * qty * self.COMMISSION_RATE
        stamp_tax = price * qty * self.STAMP_TAX_RATE if side == 'sell' else 0.0

        if side == 'buy':
            cost = price * qty + commission
            conn.execute("UPDATE accounts SET balance=balance-? WHERE id=?",
                         (cost, acc['id']))
        else:
            proceeds = price * qty - commission - stamp_tax
            conn.execute("UPDATE accounts SET balance=balance+? WHERE id=?",
                         (proceeds, acc['id']))

        order = self._save_filled(conn, acc['id'], code, name, side, 'market',
                                  price, qty, commission, stamp_tax)
        trade = self._save_trade(conn, acc['id'], order['id'], code, name, side,
                                 price, qty, commission, stamp_tax)
        self._settle_position(conn, acc, code, name, side, price, qty, trade_date)
        return order, trade

    def _execute_limit(self, conn, acc, order, trade_date):
        row = conn.execute(
            "SELECT * FROM orders WHERE id=? AND status='pending'",
            (order['id'],),
        ).fetchone()
        if row is None:
            return order, None

        commission = order['price'] * order['qty'] * self.COMMISSION_RATE
        stamp_tax = (order['price'] * order['qty'] * self.STAMP_TAX_RATE
                     if order['side'] == 'sell' else 0.0)

        if order['side'] == 'buy':
            cost = order['price'] * order['qty'] + commission
            conn.execute("UPDATE accounts SET frozen=frozen-? WHERE id=?",
                         (cost, acc['id']))
        else:
            conn.execute(
                "UPDATE positions SET frozen_qty=frozen_qty-?"
                " WHERE account_id=? AND code=?",
                (order['qty'], acc['id'], order['code']),
            )
            err = self._validate_sell(conn, acc, order['code'],
                                      order['price'], order['qty'], trade_date)
            if err:
                conn.execute(
                    "UPDATE positions SET frozen_qty=frozen_qty+?"
                    " WHERE account_id=? AND code=?",
                    (order['qty'], acc['id'], order['code']),
                )
                return order, None
            proceeds = order['price'] * order['qty'] - commission - stamp_tax
            conn.execute("UPDATE accounts SET balance=balance+? WHERE id=?",
                         (proceeds, acc['id']))

        order = self._save_filled(conn, acc['id'], order['code'], order['name'],
                                  order['side'], 'limit', order['price'],
                                  order['qty'], commission, stamp_tax,
                                  existing_id=order['id'])
        trade = self._save_trade(conn, acc['id'], order['id'], order['code'],
                                 order['name'], order['side'], order['price'],
                                 order['qty'], commission, stamp_tax)
        self._settle_position(conn, acc, order['code'], order['name'],
                              order['side'], order['price'], order['qty'],
                              trade_date)
        return order, trade

    def _save_pending(self, conn, acc, code, name, side, price, qty):
        cur = conn.execute(
            """INSERT INTO orders (account_id, code, name, side, order_type,
               price, qty, status)
               VALUES (?, ?, ?, ?, 'limit', ?, ?, 'pending')""",
            (acc['id'], code, name, side, price, qty),
        )
        oid = cur.lastrowid

        if side == 'buy':
            cost = price * qty * (1 + self.COMMISSION_RATE)
            conn.execute(
                "UPDATE accounts SET balance=balance-?, frozen=frozen+? WHERE id=?",
                (cost, cost, acc['id']),
            )
        else:
            conn.execute(
                "UPDATE positions SET frozen_qty=frozen_qty+?"
                " WHERE account_id=? AND code=?",
                (qty, acc['id'], code),
            )

        return make_order(
            conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())

    def _save_filled(self, conn, account_id, code, name, side, order_type,
                     price, qty, commission, stamp_tax, existing_id=None):
        if existing_id:
            conn.execute(
                """UPDATE orders SET status='filled', filled_qty=qty, filled_price=?,
                   commission=?, stamp_tax=?, updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (price, commission, stamp_tax, existing_id),
            )
            oid = existing_id
        else:
            cur = conn.execute(
                """INSERT INTO orders (account_id, code, name, side, order_type,
                   price, qty, filled_qty, filled_price, status, commission, stamp_tax)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'filled', ?, ?)""",
                (account_id, code, name, side, order_type, price, qty,
                 qty, price, commission, stamp_tax),
            )
            oid = cur.lastrowid
        return make_order(
            conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())

    def _save_trade(self, conn, account_id, order_id, code, name, side,
                    price, qty, commission, stamp_tax):
        cur = conn.execute(
            """INSERT INTO trades (account_id, order_id, code, name, side,
               price, qty, commission, stamp_tax)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, order_id, code, name, side, price, qty,
             commission, stamp_tax),
        )
        return make_trade(
            conn.execute("SELECT * FROM trades WHERE id=?",
                         (cur.lastrowid,)).fetchone())

    def _settle_position(self, conn, acc, code, name, side, price, qty, trade_date):
        if side == 'buy':
            pos = conn.execute(
                "SELECT * FROM positions WHERE account_id=? AND code=?",
                (acc['id'], code),
            ).fetchone()
            if pos:
                new_qty = pos['qty'] + qty
                new_cost = ((pos['cost_price'] * pos['qty'] + price * qty) / new_qty
                            if new_qty > 0 else 0.0)
                conn.execute(
                    """UPDATE positions SET qty=?, cost_price=?, current_price=?,
                       market_value=qty*?, last_buy_date=?
                       WHERE account_id=? AND code=?""",
                    (new_qty, new_cost, price, price, trade_date, acc['id'], code),
                )
            else:
                conn.execute(
                    """INSERT INTO positions (account_id, code, name, qty,
                       cost_price, current_price, market_value, last_buy_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (acc['id'], code, name, qty, price, price, qty * price, trade_date),
                )
        else:
            conn.execute(
                "UPDATE positions SET qty=qty-? WHERE account_id=? AND code=?",
                (qty, acc['id'], code),
            )
            conn.execute(
                "DELETE FROM positions WHERE account_id=? AND code=? AND qty<=0",
                (acc['id'], code),
            )
