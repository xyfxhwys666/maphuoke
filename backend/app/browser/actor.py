from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
from threading import Event, RLock, Thread
from typing import TypeVar

T = TypeVar('T')


class BrowserCommandTimeout(TimeoutError):
    """Raised when a browser command does not finish within its deadline."""


@dataclass
class _Command[T]:
    function: Callable[[], T]
    completed: Event
    result: T | None = None
    error: BaseException | None = None


class BrowserActor:
    """Run browser-bound operations in FIFO order on one thread."""

    def __init__(self) -> None:
        self._commands: Queue[_Command[object] | None] = Queue()
        self._closed = False
        self._state_lock = RLock()
        self._thread = self._new_worker(self._commands)

    def submit(self, function: Callable[[], T], *, timeout: float | None = None) -> T:
        if self._closed:
            raise RuntimeError('browser actor is closed')
        command: _Command[T] = _Command(function=function, completed=Event())
        with self._state_lock:
            self._commands.put(command)  # type: ignore[arg-type]
        if not command.completed.wait(timeout):
            self._replace_timed_out_worker()
            raise BrowserCommandTimeout('browser command timed out')
        if command.error is not None:
            raise command.error
        return command.result  # type: ignore[return-value]

    def close(self) -> None:
        if self._closed:
            return
        with self._state_lock:
            self._closed = True
            commands = self._commands
            thread = self._thread
            commands.put(None)
        thread.join(timeout=2)

    def _new_worker(self, commands: Queue[_Command[object] | None]) -> Thread:
        worker = Thread(
            target=self._worker,
            args=(commands,),
            name='mapsearch-browser-actor',
            daemon=True,
        )
        worker.start()
        return worker

    def _replace_timed_out_worker(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            old_commands = self._commands
            old_commands.put(None)
            self._commands = Queue()
            self._thread = self._new_worker(self._commands)

    def _worker(self, commands: Queue[_Command[object] | None]) -> None:
        while True:
            command = commands.get()
            if command is None:
                return
            try:
                command.result = command.function()
            except BaseException as exc:  # noqa: BLE001 - propagate command failures to the caller
                command.error = exc
            finally:
                command.completed.set()
