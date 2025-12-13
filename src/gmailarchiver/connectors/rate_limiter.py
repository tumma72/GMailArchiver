"""Adaptive rate limiter using token bucket algorithm.

This module provides rate limiting for Gmail API requests with dynamic
adjustment based on API responses (429 errors, server errors).
"""

import asyncio
import random
import time
from dataclasses import dataclass, field


@dataclass
class AdaptiveRateLimiter:
    """Token bucket rate limiter with adaptive backoff.

    Uses token bucket algorithm for smooth rate limiting with burst capability.
    Adapts rate based on API responses:
    - On success: gradually restore rate toward baseline
    - On 429: reduce rate and wait for Retry-After
    - On 5xx: short backoff without rate reduction (transient)

    Attributes:
        max_tokens: Maximum burst capacity (default: 20)
        refill_rate: Tokens per second baseline (default: 10)
        min_refill_rate: Floor rate when heavily throttled (default: 1)
        backoff_factor: Rate reduction on 429 (default: 0.5)
        recovery_threshold: Successes before rate increase (default: 10)
    """

    max_tokens: float = 20.0
    refill_rate: float = 10.0
    min_refill_rate: float = 1.0
    backoff_factor: float = 0.5
    recovery_threshold: int = 10

    # Internal state (using field with default_factory for mutable defaults)
    tokens: float = field(default=20.0, init=False)
    _last_refill: float = field(default_factory=time.monotonic, init=False)
    _consecutive_successes: int = field(default=0, init=False)
    _baseline_rate: float = field(default=10.0, init=False)

    def __post_init__(self) -> None:
        """Initialize internal state after dataclass init."""
        self.tokens = self.max_tokens
        self._baseline_rate = self.refill_rate

    def _refill(self) -> None:
        """Refill tokens based on time elapsed."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now

        # Add tokens based on elapsed time and current refill rate
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary.

        This method will block until a token is available.
        """
        while True:
            self._refill()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            # Wait a bit and try again
            await asyncio.sleep(0.1)

    def on_success(self) -> None:
        """Record successful request.

        Increments success counter and may increase rate if threshold reached.
        """
        self._consecutive_successes += 1

        if self._consecutive_successes >= self.recovery_threshold:
            # Increase rate by 10%, up to baseline
            self.refill_rate = min(self.refill_rate * 1.1, self._baseline_rate)
            self._consecutive_successes = 0

    def on_rate_limit(self, retry_after: float | None = None) -> float:
        """Handle 429 rate limit error.

        Reduces refill rate and returns wait time.

        Args:
            retry_after: Value from Retry-After header, if present

        Returns:
            Time to wait before retrying (seconds)
        """
        self._consecutive_successes = 0

        # Reduce rate, but not below minimum
        self.refill_rate = max(self.refill_rate * self.backoff_factor, self.min_refill_rate)

        # Return retry_after if provided, otherwise exponential backoff
        if retry_after is not None:
            return retry_after

        # Random backoff between 1-4 seconds
        return random.uniform(1.0, 4.0)

    def on_server_error(self) -> float:
        """Handle 5xx server error.

        Does NOT reduce rate (transient error), but returns backoff time.

        Returns:
            Time to wait before retrying (seconds)
        """
        # Don't reset success counter for transient errors
        # Don't reduce rate - server errors are transient

        # Short random backoff
        return random.uniform(0.5, 2.0)
