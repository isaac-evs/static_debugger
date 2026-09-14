"""
This module is used to observe program state during an execution.
The observed state is used collect the events that happened during
the execution of the bugged program.

Originally based on The Debugging Book's `sys.settrace`-based Tracer.
Andreas Zeller: "The Debugging Book". Retrieved 2022-02-02 19:00:00-06:00.
@book{debuggingbook2021,
    author = {Andreas Zeller},
    title = {The Debugging Book},
    year = {2021},
    publisher = {CISPA Helmholtz Center for Information Security},
    howpublished = {\\url{https://www.debuggingbook.org/}},
    note = {Retrieved 2022-02-02 19:00:00-06:00},
    url = {https://www.debuggingbook.org/},
    urldate = {2021-10-13 13:24:19+02:00}
}

`sys.settrace` hijacks the interpreter's evaluation loop for every frame
of every thread, and hands the tracer a full frame object on every single
event -- on iterative/recursive code this routinely costs 50x-100x native
execution speed. Since we now require Python 3.12+, tracing is done with
`sys.monitoring` (PEP 669) instead: events are only routed to us for the
handful of event kinds we actually care about, and the interpreter can
disable instrumentation at call sites we don't need, at near-native speed.
`sys.settrace` is kept only as a defensive fallback for interpreters where
`sys.monitoring` is unavailable.
"""
import sys
from types import FrameType, TracebackType
from typing import Any, Callable, Optional, Type, TextIO

from model.debugger.StackInspector import StackInspector

_HAS_MONITORING = hasattr(sys, 'monitoring')


class Tracer(StackInspector):
    """A class for tracing a piece of code. Use as `with Tracer(): block()`"""

    # Each Tracer instance gets its own monitoring tool slot while active,
    # so nested/sequential tracers never fight over the same id.
    _TOOL_NAME = "AbinDebugger"
    _CANDIDATE_TOOL_IDS = (
        (sys.monitoring.COVERAGE_ID, sys.monitoring.PROFILER_ID, sys.monitoring.OPTIMIZER_ID, 3, 4)
        if _HAS_MONITORING else ()
    )

    def __init__(self, *, file: TextIO = sys.stdout) -> None:
        """Trace a block of code, sending logs to `file` (default: stdout)"""
        self.original_trace_function: Optional[Callable] = None
        self.file = file
        self._tool_id: Optional[int] = None

    def traceit(self, frame: FrameType, event: str, arg: Any) -> None:
        """Tracing function. To be overridden in subclasses."""
        self.log(event, frame.f_lineno, frame.f_code.co_name, frame.f_locals)

    def _traceit(self, frame: FrameType, event: str, arg: Any) -> Optional[Callable]:
        """Internal tracing function."""
        if self.our_frame(frame):
            # Do not trace our own methods
            pass
        else:
            self.traceit(frame, event, arg)
        return self._traceit

    def log(self, *objects: Any,
            sep: str = ' ', end: str = '\n',
            flush: bool = True) -> None:
        """
        Like `print()`, but always sending to `file` given at initialization,
        and flushing by default.
        """
        print(*objects, sep=sep, end=end, file=self.file, flush=flush)

    # -- sys.monitoring (PEP 669) callbacks --
    # These don't receive a frame directly (that's the whole point -- the
    # interpreter avoids building one when no tool asks for it), so we grab
    # the caller's frame ourselves, once, only for the events we registered.

    def _on_line(self, code: Any, line_number: int) -> None:
        self._traceit(sys._getframe(1), 'line', None)

    def _on_call(self, code: Any, instruction_offset: int) -> None:
        self._traceit(sys._getframe(1), 'call', None)

    def _on_return(self, code: Any, instruction_offset: int, retval: Any) -> None:
        self._traceit(sys._getframe(1), 'return', retval)

    def _on_exception(self, code: Any, instruction_offset: int, exception: BaseException) -> None:
        exc_info = (type(exception), exception, exception.__traceback__)
        self._traceit(sys._getframe(1), 'exception', exc_info)

    def _enable_monitoring(self) -> bool:
        """ Claims a free monitoring tool id and registers callbacks.
        :rtype: bool -- whether monitoring was successfully enabled.
        """
        monitoring = sys.monitoring
        for tool_id in self._CANDIDATE_TOOL_IDS:
            try:
                monitoring.use_tool_id(tool_id, self._TOOL_NAME)
            except ValueError:
                continue
            self._tool_id = tool_id
            break
        if self._tool_id is None:
            return False

        events = monitoring.events
        monitoring.register_callback(self._tool_id, events.LINE, self._on_line)
        monitoring.register_callback(self._tool_id, events.PY_START, self._on_call)
        monitoring.register_callback(self._tool_id, events.PY_RETURN, self._on_return)
        monitoring.register_callback(self._tool_id, events.RAISE, self._on_exception)
        monitoring.set_events(self._tool_id,
            events.LINE | events.PY_START | events.PY_RETURN | events.RAISE)
        return True

    def _disable_monitoring(self) -> None:
        monitoring = sys.monitoring
        monitoring.set_events(self._tool_id, monitoring.events.NO_EVENTS)
        for event in (monitoring.events.LINE, monitoring.events.PY_START,
                      monitoring.events.PY_RETURN, monitoring.events.RAISE):
            monitoring.register_callback(self._tool_id, event, None)
        monitoring.free_tool_id(self._tool_id)
        self._tool_id = None

    def __enter__(self) -> Any:
        """Called at begin of `with` block. Turn tracing on."""
        if not (_HAS_MONITORING and self._enable_monitoring()):
            # No sys.monitoring tool slot available (or unsupported
            # interpreter): fall back to the legacy tracing hook.
            self.original_trace_function = sys.gettrace()
            sys.settrace(self._traceit)
        return self

    def __exit__(self, exc_tp: Type, exc_value: BaseException,
                 exc_traceback: TracebackType) -> Optional[bool]:
        """
        Called at end of `with` block. Turn tracing off.
        Return `None` if ok, not `None` if internal error.
        """
        if self._tool_id is not None:
            self._disable_monitoring()
        else:
            sys.settrace(self.original_trace_function)

        # Note: we must return a non-True value here,
        # such that we re-raise all exceptions
        if self.is_internal_error(exc_tp, exc_value, exc_traceback):
            return False  # internal error
        else:
            return None  # all ok
