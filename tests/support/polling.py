"""A small polling helper shared by tests that wait on another thread.

Control-plane tests can't just call a synchronous method and assert on the
result -- a push notification (`notify_run_status`, `notify_breakpoint`)
arrives asynchronously on the client's background thread, so the test has to
wait for it rather than read it immediately after sending the triggering
request.
"""

from __future__ import annotations

import time
from collections.abc import Callable


def poll_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll `predicate` until it's true or `timeout` seconds have elapsed.

    Args:
        predicate: Zero-argument callable checked repeatedly.
        timeout: Maximum time to poll, in seconds.

    Returns:
        The final result of `predicate()` -- True if it became true within
        `timeout`, otherwise its last (false) value.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
