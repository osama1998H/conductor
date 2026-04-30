"""RetryPolicy: declarative configuration for retry behavior on a job.

A policy decides (a) how long to wait before the next retry of a given attempt,
and (b) whether a given exception should be retried at all.

Stamped into the JobMessage at dispatch time so in-flight retries stay pinned
to their dispatch-time policy across redeploys.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff: Literal["exponential", "linear", "fixed"] = "exponential"
    base_delay_seconds: int = 2
    max_delay_seconds: int = 600
    jitter: Literal["none", "full", "equal"] = "full"
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    no_retry_on: tuple[type[BaseException], ...] = ()

    def compute_next_delay(self, attempt: int) -> float:
        """Return seconds to wait before retry attempt `attempt + 1`."""
        if self.backoff == "exponential":
            base = self.base_delay_seconds * (2 ** (attempt - 1))
        elif self.backoff == "linear":
            base = self.base_delay_seconds * attempt
        else:  # "fixed"
            base = self.base_delay_seconds

        capped = min(base, self.max_delay_seconds)

        if self.jitter == "none":
            return float(capped)
        if self.jitter == "full":
            return random.uniform(0, capped)
        # "equal"
        return capped / 2 + random.uniform(0, capped / 2)

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        """True iff exc matches retry_on, doesn't match no_retry_on, and attempt < max_attempts."""
        if attempt >= self.max_attempts:
            return False
        if self.no_retry_on and isinstance(exc, self.no_retry_on):
            return False
        if not isinstance(exc, self.retry_on):
            return False
        return True
