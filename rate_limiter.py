import threading
import time
from typing import Dict


class TokenBucketRateLimiter:
    """Simple per-provider token bucket rate limiter.

    Each provider has a capacity of 1 token and is refilled at `rate` tokens per second.
    acquire(provider) will block until a token is available.
    """

    def __init__(self, rate: float = 1.0):
        self.rate = float(rate)
        self.lock = threading.Lock()
        # state per provider: { provider: (tokens, last_ts) }
        self._state: Dict[str, tuple] = {}

    def _ensure_provider(self, provider: str) -> None:
        if provider not in self._state:
            self._state[provider] = (1.0, time.time())

    def acquire(self, provider: str) -> None:
        self._ensure_provider(provider)
        while True:
            with self.lock:
                tokens, last = self._state.get(provider, (1.0, time.time()))
                now = time.time()
                # refill
                tokens = min(1.0, tokens + (now - last) * self.rate)
                if tokens >= 1.0:
                    # consume
                    self._state[provider] = (tokens - 1.0, now)
                    return
                # update last timestamp and compute time to wait
                self._state[provider] = (tokens, now)
                needed = (1.0 - tokens) / self.rate if self.rate > 0 else 0.0
            # sleep outside lock
            time.sleep(max(0.0, needed))


# module-level default limiter
default_limiter = TokenBucketRateLimiter(rate=1.0)


def acquire(provider: str) -> None:
    default_limiter.acquire(provider)
