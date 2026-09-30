import threading

import config
import logger as AbinLogging

# Per-test timeout: a daemon threading.Timer that flips
# config.TIMEOUT_SIGNAL_RECEIVED, which AbinCollector.collect() polls on
# every traced event and turns into a TimeoutError on the thread actually
# running the candidate. (This used signal.SIGALRM/setitimer before, which
# don't exist on Windows -- and only ever set the flag anyway, so a timer
# thread does the same job on every platform.)
_timer_lock = threading.Lock()
_timer = None
_timer_generation = 0


def _on_timeout(generation: int) -> None:
    """ Timer callback. Ignored if the test it was armed for has already
    finished (cancel bumps the generation under the same lock), so a late
    fire can never leak a timeout into a later, unrelated test. """
    with _timer_lock:
        if generation != _timer_generation:
            return
        config.TIMEOUT_SIGNAL_RECEIVED = 1
    AbinLogging.debugging_logger.info("Current test timeout reached!")


def start_test_timer(seconds: float) -> None:
    """ Arms the per-test timeout, replacing any timer still pending. """
    global _timer, _timer_generation
    with _timer_lock:
        if _timer is not None:
            _timer.cancel()
        _timer_generation += 1
        config.TIMEOUT_SIGNAL_RECEIVED = 0
        _timer = threading.Timer(seconds, _on_timeout, args=(_timer_generation,))
        _timer.daemon = True
        _timer.start()


def cancel_test_timer() -> None:
    """ Disarms the per-test timeout (safe to call when none is armed). """
    global _timer, _timer_generation
    with _timer_lock:
        _timer_generation += 1
        if _timer is not None:
            _timer.cancel()
            _timer = None
