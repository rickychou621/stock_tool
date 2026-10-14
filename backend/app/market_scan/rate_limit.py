"""One paced budget shared by all stage-three workers in the single backend instance."""

import time
from threading import Lock


class RateLimiter:
    def __init__(self, requests_per_minute, clock=time.monotonic, sleep=time.sleep):
        if requests_per_minute <= 0:
            raise ValueError("請求額度必須為正數")
        self.interval = 60 / requests_per_minute
        self.clock, self.sleep, self.lock = clock, sleep, Lock()
        # Conservative cold start: do not burst immediately after a process restart.
        self.next_at = clock() + self.interval

    def acquire(self):
        with self.lock:
            delay = self.next_at - self.clock()
            if delay > 0:
                self.sleep(delay)
            self.next_at = self.clock() + self.interval
