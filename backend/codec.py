# -*- coding: utf-8 -*-
"""A股/指数/港股 代码规范化(codec)。

把"这块代码怎么存/怎么传给数据源"集中到一处，避免调用方各自拼前缀导致
索引/股票撞库(如 000001 平安银行 vs 上证指数)。

约定(与现有库一致，不做全库迁移)：
- 股票(stock): 规范存储码 = 裸 6 位，如 600036；剥掉 .SH/.SZ/.SS 后缀与 sh/sz 前缀
- 指数(index): 规范存储码 = sh/sz 前缀，如 sh000001 / sz399001
- 港股(hk):    hk 前缀 + 5 位，如 hk00700
- auto: 显式带 sh/sz/bj/hk 前缀则保留；否则视为股票裸码
- 000001 裸码歧义(既是平安银行又是上证指数)须显式传 kind，不做自动猜测

另提供 ak_symbol() 把规范码转成 akshare 需要的 symbol(股票带 sh/sz 前缀)。
"""
from __future__ import annotations

KIND_STOCK = "stock"
KIND_INDEX = "index"
KIND_HK = "hk"
KIND_AUTO = "auto"

_PREFIX_INDEX_DEFAULT = "sh"
_SZ_INDEX_PREFIXES = ("399",)  # 深证指数系


def _has_prefix(s: str, pfx: str, body: str) -> bool:
    return s[: len(pfx)].lower() == pfx and body.isdigit()


def strip_suffix(code: str) -> tuple[str, str]:
    """返回 (裸码, 交易所前缀或'')；如 600036.SH -> ('600036','sh')。"""
    s = (code or "").strip()
    low = s.lower()
    for suf, pfx in ((".sh", "sh"), (".ss", "sh"), (".sz", "sz"), (".hk", "hk")):
        if low.endswith(suf):
            return s[: -len(suf)], pfx
    return s, ""


def normalize_a_code(code: str, kind: str = KIND_AUTO) -> str:
    """规范化代码为规范存储码。kind: stock | index | hk | auto。"""
    s = str(code or "").strip()
    if not s:
        return s
    low = s.lower()

    # 1) 显式交易所前缀(小写 sh/sz/bj/hk + 数字体)
    for pfx in ("sh", "sz", "bj", "hk"):
        body = s[len(pfx):]
        if low.startswith(pfx) and body.isdigit():
            if kind == KIND_STOCK and pfx in ("sh", "sz", "bj"):
                return body                      # 股票剥前缀 → 裸6位
            return pfx + body                    # index/hk/auto 保留前缀
    # 2) 带 .SH/.SS/.SZ/.HK 后缀
    bare, pfx = strip_suffix(s)
    if pfx:
        if kind == KIND_STOCK and pfx in ("sh", "sz"):
            return bare
        if pfx == "hk":
            return "hk" + bare.zfill(5)
        return pfx + bare                        # index
    # 3) 纯数字
    if s.isdigit():
        if kind == KIND_INDEX:
            return ("sz" if s.startswith(_SZ_INDEX_PREFIXES) else _PREFIX_INDEX_DEFAULT) + s
        if kind == KIND_HK:
            return "hk" + s.zfill(5)
        return s                                  # stock / auto → 裸码
    return s


def ak_symbol(code: str, kind: str = KIND_STOCK) -> str:
    """转成 akshare 接口需要的 symbol。
    - 股票: sh600036 / sz000001(ak.stock_zh_a_daily 需要交易所前缀)
    - 指数: sh000001 / sz399001(ak.stock_zh_index_daily 已带前缀)
    """
    if kind == KIND_STOCK:
        c = normalize_a_code(code, KIND_AUTO)
        if c[:2] in ("sh", "sz", "bj"):
            return c
        # 低位数股票规则与现有 ak_fetch_kline 保持一致: 6/9 开头 → 沪
        return ("sh" if c.startswith(("6", "9")) else "sz") + c
    if kind == KIND_INDEX:
        return normalize_a_code(code, KIND_INDEX)
    return normalize_a_code(code, kind)
