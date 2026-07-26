# -*- coding: utf-8 -*-
"""End-to-end test shell for TradeEngine. Run with: python -m backend.trade_engine.test_shell"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.trade_engine.engine import TradeEngine

DB_PATH = os.path.join(os.path.dirname(__file__), "test.db")

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


def setup():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    return TradeEngine(DB_PATH)


def test_create_account():
    print("\n=== 创建账户 ===")
    engine = setup()
    aid = engine.create_account("测试账户", 100000)
    acc = engine.get_account(aid)
    check("账户ID正确", aid == 1)
    check("账户名", acc['name'] == "测试账户")
    check("初始资金10万", acc['initial_capital'] == 100000)
    check("余额=初始资金", acc['balance'] == 100000)
    check("冻结为0", acc['frozen'] == 0)
    return engine, aid


def test_market_buy(engine, aid):
    print("\n=== 市价买入 ===")
    order, trade = engine.place_order(
        aid, "600519", "贵州茅台", "buy", "market",
        price=0, qty=100, current_price=250.0,
    )
    check("下单成功", order is not None and isinstance(order, dict))
    check("成交记录已生成", trade is not None and isinstance(trade, dict))
    check("订单状态filled", order['status'] == 'filled')
    check("成交价=当前价", trade['price'] == 250.0)
    check("成交数量100股", trade['qty'] == 100)

    acc = engine.get_account(aid)
    cost = 250 * 100 * (1 + 0.0003)
    expected_balance = 100000 - cost
    check("余额减少手续费", abs(acc['balance'] - expected_balance) < 0.01)

    positions = engine.get_positions(aid)
    check("持仓出现", len(positions) == 1)
    check("持仓代码", positions[0]['code'] == "600519")
    check("持仓100股", positions[0]['qty'] == 100)
    check("成本价=成交价", positions[0]['cost_price'] == 250.0)
    return engine, aid


def test_limit_order_pending(engine, aid):
    print("\n=== 限价挂单 ===")
    order, trade = engine.place_order(
        aid, "000858", "五粮液", "buy", "limit",
        price=150.0, qty=100, current_price=160.0,
    )
    check("限价单创建", order is not None)
    check("未立即成交", trade is None)
    check("状态pending", order['status'] == 'pending')
    check("委托价150", order['price'] == 150.0)

    acc = engine.get_account(aid)
    frozen = 150.0 * 100 * (1 + 0.0003)
    check("资金已冻结", acc['frozen'] > 0)
    check("冻结金额正确", abs(acc['frozen'] - frozen) < 0.1)
    return engine, aid, order['id']


def test_cancel_order(engine, aid, order_id):
    print("\n=== 撤销限价单 ===")
    acc_before = engine.get_account(aid)
    ok, err = engine.cancel_order(order_id)
    check("撤单成功", ok and err is None)
    acc_after = engine.get_account(aid)
    check("冻结已清零", acc_after['frozen'] == 0)
    check("资金已退还", acc_after['balance'] > acc_before['balance'])

    orders = engine.get_orders(aid, status='cancelled')
    check("订单状态cancelled", any(o['id'] == order_id for o in orders))


def test_limit_order_fill(engine, aid):
    print("\n=== 限价单触发成交 ===")
    order, _ = engine.place_order(
        aid, "000858", "五粮液", "buy", "limit",
        price=160.0, qty=100, current_price=170.0,
    )
    check("限价买单创建", order is not None)
    check("状态pending", order['status'] == 'pending')

    engine.check_orders(aid, "000858", 160.0)
    trades = engine.get_trades(aid)
    filled = [t for t in trades if t['order_id'] == order['id']]
    check("已成交", len(filled) == 1)
    check("成交价=委托价", filled[0]['price'] == 160.0)
    check("成交100股", filled[0]['qty'] == 100)

    positions = engine.get_positions(aid)
    pos = [p for p in positions if p['code'] == "000858"]
    check("新增持仓", len(pos) == 1)
    check("持仓100股", pos[0]['qty'] == 100)
    return engine, aid


def test_sell_limit_order(engine, aid):
    print("\n=== 限价卖单 ===")
    order, _ = engine.place_order(
        aid, "600519", "贵州茅台", "sell", "limit",
        price=300.0, qty=100, trade_date="2026-07-29",
    )
    check("卖单创建", order is not None and isinstance(order, dict))
    check("状态pending", order['status'] == 'pending')

    engine.check_orders(aid, "600519", 310.0, trade_date="2026-07-29")
    trades = engine.get_trades(aid)
    filled = [t for t in trades if t['order_id'] == order['id']]
    check("卖单成交", len(filled) == 1)
    check("成交价300", filled[0]['price'] == 300.0)
    check("有印花税", filled[0]['stamp_tax'] > 0)

    positions = engine.get_positions(aid)
    remain = [p for p in positions if p['code'] == "600519"]
    check("茅台已清仓", len(remain) == 0)
    return engine, aid


def test_t1_restriction(engine, aid):
    print("\n=== T+1限制 ===")
    engine.place_order(aid, "300750", "宁德时代", "buy", "market",
                       price=0, qty=100, current_price=400.0, trade_date="2026-07-28")

    order, msg = engine.place_order(
        aid, "300750", "宁德时代", "sell", "market",
        price=0, qty=100, current_price=420.0, trade_date="2026-07-28",
    )
    check("当日卖出被拒", order is None and "T+1" in msg)

    order2, _ = engine.place_order(
        aid, "300750", "宁德时代", "sell", "market",
        price=0, qty=100, current_price=420.0, trade_date="2026-07-29",
    )
    check("T+1后可卖出", order2 is not None and order2['status'] == 'filled')


def test_summary(engine, aid):
    print("\n=== 账户摘要 ===")
    summary = engine.get_summary(aid)
    check("摘要存在", summary is not None)
    check("总资产正常", summary['total_assets'] > 0)
    check("总盈亏计算", isinstance(summary['total_profit'], float))
    check("持仓计数", summary['positions'] >= 0)

    print(f"\n  总资产: {summary['total_assets']:,.2f}")
    print(f"  总盈亏: {summary['total_profit']:,.2f} ({summary['total_profit_pct']:.2f}%)")
    print(f"  可用: {summary['balance']:,.2f}  冻结: {summary['frozen']:,.2f}")
    print(f"  市值: {summary['market_value']:,.2f}")


def test_reset_account(engine, aid):
    print("\n=== 重置账户 ===")
    engine.reset_account(aid)
    acc = engine.get_account(aid)
    check("余额恢复初始", acc['balance'] == acc['initial_capital'])
    check("冻结清零", acc['frozen'] == 0)
    positions = engine.get_positions(aid)
    check("持仓清空", len(positions) == 0)
    trades = engine.get_trades(aid)
    check("成交清空", len(trades) == 0)


def test_insufficient_balance(engine, aid):
    print("\n=== 资金不足 ===")
    order, msg = engine.place_order(
        aid, "600519", "贵州茅台", "buy", "market",
        price=0, qty=1000000, current_price=1800.0,
    )
    check("超大买单被拒", order is None and "资金不足" in msg)


def test_invalid_sell_no_position(engine, aid):
    print("\n=== 无持仓卖出 ===")
    order, msg = engine.place_order(
        aid, "999999", "不存在", "sell", "market",
        price=0, qty=100, current_price=50.0,
    )
    check("无持仓卖出被拒", order is None and "持仓" in msg)


if __name__ == "__main__":
    engine, aid = test_create_account()
    engine, aid = test_market_buy(engine, aid)
    engine, aid, oid = test_limit_order_pending(engine, aid)
    test_cancel_order(engine, aid, oid)
    engine, aid = test_limit_order_fill(engine, aid)
    engine, aid = test_sell_limit_order(engine, aid)
    test_t1_restriction(engine, aid)
    test_summary(engine, aid)
    test_reset_account(engine, aid)
    test_insufficient_balance(engine, aid)
    test_invalid_sell_no_position(engine, aid)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print(f"\n{'='*40}")
    print(f"  通过: {passed}  失败: {failed}")
    print(f"{'='*40}")

    if failed > 0:
        sys.exit(1)
