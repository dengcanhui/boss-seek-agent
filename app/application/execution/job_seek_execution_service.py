import asyncio
import logging
from contextlib import suppress

from app.execution.worker import JobSeekWorker

from .models import JobSeekExecutionState


logger = logging.getLogger("uvicorn.error.execution")


class JobSeekExecutionService:
    """管理求职任务执行器的生命周期和状态。"""

    def __init__(self, worker: JobSeekWorker, stop_timeout: float = 10.0):
        self.worker: JobSeekWorker = worker
        self.stop_timeout: float = stop_timeout
        self._task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._last_error: str | None = None

    def get_state(self) -> JobSeekExecutionState:
        task = self._task
        return JobSeekExecutionState(
            active=task is not None and not task.done(),
            current_job_seek_task_id=self.worker.active_job_seek_task_id,
            last_error=self._last_error,
        )

    async def start(self) -> JobSeekExecutionState:
        async with self._lock:
            if self._task is not None and not self._task.done():
                return self.get_state()

            if self._task is not None:
                self._consume_finished(self._task)

            self._last_error = None
            self.worker.prepare_start()
            task = asyncio.create_task(self.worker.run_forever())
            task.add_done_callback(self._on_done)
            self._task = task

        await asyncio.sleep(0)
        return self.get_state()

    async def stop(self) -> JobSeekExecutionState:
        async with self._lock:
            task = self._task
            if task is None:
                return self.get_state()

            if task.done():
                self._consume_finished(task)
                self._task = None
                return self.get_state()

            self.worker.request_stop()

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.stop_timeout)
        except TimeoutError:
            logger.warning(
                "[execution] Worker 在 %.1fs 内未停止，强制取消后台任务",
                self.stop_timeout,
            )
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        async with self._lock:
            if self._task is task:
                self._task = None

        return self.get_state()

    async def shutdown(self) -> None:
        task = self._task
        if task is None:
            return

        try:
            await self.stop()
        except Exception:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._consume_finished(task)

    def _consume_finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self._last_error = str(error)
