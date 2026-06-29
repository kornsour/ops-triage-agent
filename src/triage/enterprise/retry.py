"""Bounded retry with exponential backoff for flaky downstream tools.

Sleep is injected so tests run instantly. Only the listed exception types are
retried; everything else propagates immediately.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
    factor: float = 2.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = lambda _s: None,
) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:  # noqa: PERF203
            last = exc
            if i == attempts - 1:
                break
            sleep(base_delay * (factor**i))
    assert last is not None
    raise last
