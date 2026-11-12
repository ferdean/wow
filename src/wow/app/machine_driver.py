"""Run a core state machine in the shell.

Runs a core state machine in the shell (AD-07, AD-22; ICD 4.4.1):
events are handled the moment they arrive, and a Tick is sent when the
machine's next deadline comes, waiting only through the Clock port.
"""

import asyncio
from collections.abc import Callable

from wow.core.machine import StateMachine
from wow.ports.clock import Clock


class MachineDriver[E, A]:
    """Feeds events to a state machine and runs its deadlines."""

    def __init__(
        self,
        machine: StateMachine[E, A],
        clock: Clock,
        perform: Callable[[list[A]], None],
        tick: E,
    ) -> None:
        self._machine = machine
        self._clock = clock
        self._perform = perform
        self._tick = tick
        self._deadline: float | None = None
        self._timer: asyncio.Task[None] | None = None

    def post(self, event: E) -> None:
        """Handle an event now."""
        actions = self._machine.handle(event, self._clock.monotonic())
        self._perform(actions)
        self._schedule()

    def close(self) -> None:
        """Stop the deadline timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._deadline = None

    def _schedule(self) -> None:
        deadline = self._machine.next_deadline()
        if deadline == self._deadline and self._timer is not None:
            return
        self.close()
        if deadline is not None:
            self._deadline = deadline
            self._timer = asyncio.get_running_loop().create_task(
                self._wake(deadline))

    async def _wake(self, deadline: float) -> None:
        await self._clock.sleep_until(deadline)
        self._timer = None
        self._deadline = None
        self.post(self._tick)
