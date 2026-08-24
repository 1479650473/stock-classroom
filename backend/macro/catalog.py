# -*- coding: utf-8 -*-
"""全球宏观目录 — 精选影响 A 股的宏观标的(不是 30 万全目录，只取 relevant 子集)。

每个指标带：fetch 方式(akshare 函数 + 参数) / 取值列 / 类别 / 单位 / 对 A 股的关联说明。
用途：作为"全球宏观 context 层"的元数据，供 provider 抓数、features 合成宏观 regime、
研究代理(生成/修订 A 股策略)时读取宏观语境。
"""
# 取值列: 各 source 返回 DataFrame 中用作"值"的列名
INDICATORS = [
    # ── 全球股市风险偏好 ──
    dict(key="sp500", name="标普500", category="equity", unit="点",
         source="index_us_stock_sina", params={"symbol": ".INX"}, col="close",
         desc="全球风险偏好/美股基准，A股外部情绪风向标"),
    dict(key="nasdaq", name="纳斯达克", category="equity", unit="点",
         source="index_us_stock_sina", params={"symbol": ".IXIC"}, col="close",
         desc="美股科技/成长风险偏好，影响 A股成长与科创板情绪"),
    dict(key="hsi", name="恒生指数", category="equity", unit="点",
         source="stock_hk_index_daily_sina", params={"symbol": "HSI"}, col="close",
         desc="港股/外资对人民币资产态度，与北向资金联动"),
    # ── 汇率/资金 ──
    dict(key="usdcny", name="美元/人民币(实时)", category="fx", unit="汇率",
         source="fx_spot_quote", params={}, col="rate",
         desc="人民币汇率(实时spot)。环境内历史源(BOC)陈旧/东财被墙，取实时水平，趋势受源限制"),
    # ── 利率/流动性 ──
    dict(key="us10y", name="美国10年期国债收益率", category="rate", unit="%",
         source="bond_zh_us_rate", params={}, col="美国国债收益率10年",
         desc="全球无风险利率/估值锚，影响成长股估值与美元资产"),
    dict(key="cn10y", name="中国10年期国债收益率", category="rate", unit="%",
         source="bond_zh_us_rate", params={}, col="中国国债收益率10年",
         desc="国内无风险利率，影响 A股股债性价比与流动性"),
    dict(key="us10y_2y", name="美债10Y-2Y期限利差", category="rate", unit="%",
         source="bond_zh_us_rate", params={}, col="美国国债收益率10年-2年",
         desc="收益率曲线斜率，衰退/复苏信号，影响全球风险资产"),
    # ── 商品/通胀 ──
    dict(key="gold", name="沪金(AU0)", category="commodity", unit="元/克",
         source="futures_main_sina", params={"symbol": "AU0"}, col="收盘价",
         desc="避险/通胀预期，与真实利率负相关，影响有色与避险情绪"),
    dict(key="oil", name="原油(SC0)", category="commodity", unit="元/桶",
         source="futures_main_sina", params={"symbol": "SC0"}, col="收盘价",
         desc="全球通胀与成本端，影响化工/能源/通胀预期"),
    dict(key="copper", name="沪铜(CU0)", category="commodity", unit="元/吨",
         source="futures_main_sina", params={"symbol": "CU0"}, col="收盘价",
         desc="经济景气铜，与A股周期/新能源/电网联动"),
    # ── 波动率/情绪(代理) ──
    dict(key="sp500_vol", name="标普已实现波动率(20日)", category="vol", unit="%",
         source="computed", params={}, col="close",
         desc="用标普收益年化波动做全球恐慌/risk-off 代理(VIX 无稳定源)"),
]

CATEGORIES = ["equity", "fx", "rate", "commodity", "vol"]

CATEGORY_CN = {
    "equity": "全球股市", "fx": "汇率资金", "rate": "利率流动性",
    "commodity": "商品通胀", "vol": "波动率情绪",
}


def indicators(category=None):
    if category:
        return [i for i in INDICATORS if i["category"] == category]
    return list(INDICATORS)


def by_key(key):
    for i in INDICATORS:
        if i["key"] == key:
            return i
    return None
