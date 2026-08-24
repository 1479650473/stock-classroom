# -*- coding: utf-8 -*-
"""数据源韧性层 — 移植自 QuantDinger 的 data_sources/rate_limiter.py。

针对 akshare/新浪等境外/国内网络脆弱的行情源：
- RateLimiter: 进程内最小间隔 + 随机抖动(可选 jitter)，避免高频请求触发限流/重置
- retry_with_backoff: 指数退避 + 抖动，可对"返回空列表"重试(akshare 常吞异常返回 [])
- get_request_headers: 随机 User-Agent 轮换 + Referer + zh-CN + Connection: close
"""
from __future__ import annotations

import random
import time
from functools import wraps
from typing import Callable, Optional, Tuple, Type

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def get_request_headers(referer: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if referer:
        headers["Referer"] = referer
    return headers


class RateLimiter:
    """进程内限流：最小间隔 + 随机抖动。"""

    def __init__(self, min_interval: float = 1.0, jitter_min: float = 0.5, jitter_max: float = 1.5):
        self.min_interval = min_interval
        self.jitter_min = jitter_min
        self.jitter_max = jitter_max
        self._last_request_time: Optional[float] = None

    def wait(self) -> float:
        wait_time = 0.0
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                time.sleep(wait_time)
        jitter = random.uniform(self.jitter_min, self.jitter_max)
        time.sleep(jitter)
        wait_time += jitter
        self._last_request_time = time.time()
        return wait_time

    def reset(self) -> None:
        self._last_request_time = None


_akshare_limiter = RateLimiter(min_interval=1.5, jitter_min=0.8, jitter_max=2.5)
_sina_limiter = RateLimiter(min_interval=1.0, jitter_min=0.4, jitter_max=1.4)


def akshare_wait() -> float:
    return _akshare_limiter.wait()


def sina_wait() -> float:
    return _sina_limiter.wait()


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.5,
    max_delay: float = 12.0,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    retry_on_empty: bool = False,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """重试装饰器。
    - exceptions: 捕获后重试
    - retry_on_empty: 返回空(list/None/falsy)也视为失败重试(适配 akshare 吞异常返回 [])
    - 指数退避 + 抖动；达到 max_attempts 后抛出最后一个异常(或返回最后一次结果)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            last_result = None
            for attempt in range(1, max_attempts + 1):
                try:
                    last_result = func(*args, **kwargs)
                    if retry_on_empty and not last_result:
                        raise _EmptyResult(f"{func.__name__} returned empty")
                    return last_result
                except exceptions as exc:
                    last_exc = exc
                    retryable = not (isinstance(exc, _EmptyResult) and retry_on_empty)
                    if attempt >= max_attempts:
                        if last_exc:
                            raise last_exc
                        return last_result
                    if not retryable:
                        continue
                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    delay *= random.uniform(0.8, 1.2)
                    if on_retry:
                        on_retry(attempt, exc)
                    time.sleep(delay)
            if last_exc:
                raise last_exc
            return last_result

        return wrapper

    return decorator


class _EmptyResult(Exception):
    pass
