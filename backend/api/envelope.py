# -*- coding: utf-8 -*-
"""Uniform API envelopes.

Success: {"code": 0, "data": ..., "message": "ok"}
Error:   {"code": <http>, "data": null, "error": {code, message, retriable}}
"""
from flask import jsonify


def ok(data=None, message="ok", **meta):
    body = {"code": 0, "data": data, "message": message}
    body.update(meta)
    return jsonify(body)


def err(http=400, code="error", message="出错了", retriable=False, details=None):
    payload = {"code": code, "message": message, "retriable": retriable}
    if details is not None:
        payload["details"] = details
    return jsonify({"code": http, "data": None, "error": payload}), http


def int_arg(raw, default, lo=0, hi=10_000):
    """安全解析 query/query int 参数(非法输入 → default, 不抛 ValueError → 500)."""
    try:
        v = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))
