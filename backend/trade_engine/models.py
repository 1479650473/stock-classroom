# -*- coding: utf-8 -*-
"""Data models for the simulated trading engine."""


ORDER_SIDES = ('buy', 'sell')
ORDER_TYPES = ('market', 'limit')
ORDER_STATUSES = ('pending', 'partial', 'filled', 'cancelled')


def make_account(row):
    """Convert a DB row (sqlite3.Row or dict) to dict."""
    return {
        'id': row['id'],
        'name': row['name'],
        'initial_capital': row['initial_capital'],
        'balance': row['balance'],
        'frozen': row['frozen'],
        'total_profit': row['total_profit'],
        'is_active': row['is_active'],
        'created_at': row['created_at'],
    }


def make_order(row):
    return {
        'id': row['id'],
        'account_id': row['account_id'],
        'code': row['code'],
        'name': row['name'] or '',
        'side': row['side'],
        'order_type': row['order_type'],
        'price': row['price'],
        'qty': row['qty'],
        'filled_qty': row['filled_qty'],
        'filled_price': row['filled_price'],
        'status': row['status'],
        'commission': row['commission'],
        'stamp_tax': row['stamp_tax'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def make_position(row):
    return {
        'id': row['id'],
        'account_id': row['account_id'],
        'code': row['code'],
        'name': row['name'] or '',
        'qty': row['qty'],
        'frozen_qty': row['frozen_qty'],
        'cost_price': row['cost_price'],
        'current_price': row['current_price'],
        'market_value': row['market_value'],
        'float_pnl': row['float_pnl'],
        'last_buy_date': row['last_buy_date'] or '',
    }


def make_trade(row):
    return {
        'id': row['id'],
        'account_id': row['account_id'],
        'order_id': row['order_id'],
        'code': row['code'],
        'name': row['name'] or '',
        'side': row['side'],
        'price': row['price'],
        'qty': row['qty'],
        'commission': row['commission'],
        'stamp_tax': row['stamp_tax'],
        'traded_at': row['traded_at'],
    }
