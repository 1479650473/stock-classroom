# -*- coding: utf-8 -*-
"""基金套利模块（LOF 折溢价）。

数据：新浪（LOF 名单/实时快照）+ 腾讯（场内日线）+ 东财（单位净值/费率/申购门槛）。
存储：data/fund_arb.db（lof_list / lof_daily / fund_nav / fund_fee / fund_purchase / arb_meta）。
计算：折溢价率 = 场内收盘价 / 单位净值 - 1（两者都取「原始」口径，分红除权时同步下降，比值仍可比）。
"""
