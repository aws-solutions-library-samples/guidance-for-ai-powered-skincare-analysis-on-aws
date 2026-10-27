"""One deadline/retry ledger shared by all work in a step search."""

import math
import time
from collections.abc import Callable

from .errors import SearchDeadlineExceeded, SearchUnavailable


class SearchBudget:
    def __init__(
        self, seconds: float = 1.2, *, started: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not math.isfinite(seconds) or not 0 < seconds <= 1.2:
            raise ValueError("Search budget must be positive and at most 1.2 seconds")
        self.clock = clock
        self.sleep = sleep
        self.started = clock() if started is None else started
        if not math.isfinite(self.started) or self.started > clock():
            raise ValueError("Scheduled arrival cannot be in the future")
        self.deadline = self.started + seconds
        self.retries = 0

    def remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise SearchDeadlineExceeded("Search deadline exhausted")
        return remaining

    def require(self, seconds: float) -> None:
        if self.remaining() < seconds:
            raise SearchDeadlineExceeded("Insufficient remaining search budget")

    def retry(self) -> None:
        if self.retries >= 1:
            raise SearchUnavailable("Search dependency retry budget exhausted")
        self.require(0.010)
        self.retries += 1
        self.sleep(0.010)
        self.remaining()

    @property
    def elapsed_ms(self) -> float:
        return max(0, (self.clock() - self.started) * 1000)
