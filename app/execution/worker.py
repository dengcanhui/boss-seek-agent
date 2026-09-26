import asyncio
import logging
from contextlib import suppress

from app.domain.search.enums import JobSeekTaskStatus
from app.execution.boss.executor import BossJobExecutor
from app.infrastructure.database.repositories.job_seek_task_repository import JobSeekTaskRepository


logger = logging.getLogger("uvicorn.error.worker")


class JobSeekWorker:
    """顺序消费 pending 求职任务。

    Worker 只负责任务领取、执行和状态流转；具体浏览器行为由 ``BossJobExecutor`` 完成。
    停止 Worker 时，当前 running 任务会变为 stopped；下次启动只继续消费 pending。
    """

    def __init__(
        self,
        repository: JobSeekTaskRepository,
        executor: BossJobExecutor,
        poll_interval: float = 2.0,
        control_poll_interval: float = 0.1,
    ):
        self.repository: JobSeekTaskRepository = repository
        self.executor: BossJobExecutor = executor
        self.poll_interval: float = poll_interval
        self.control_poll_interval: float = control_poll_interval
        self._stop_event: asyncio.Event = asyncio.Event()
        self._active_execution: asyncio.Task[None] | None = None
        self._active_job_seek_task_id: int | None = None
        self._running: bool = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def active_job_seek_task_id(self) -> int | None:
        return self._active_job_seek_task_id

    def prepare_start(self) -> None:
        if self._running:
            raise RuntimeError("JobSeekWorker 已经在运行。")
        logger.info("[worker] 准备启动执行器")
        self._stop_event.clear()

    def request_stop(self) -> None:
        logger.info("[worker] 收到停止执行器请求")
        self._stop_event.set()

    async def run_once(self) -> bool:
        if self._stop_event.is_set():
            return False

        job_seek_task = self.repository.claim_next()
        if job_seek_task is None:
            return False

        logger.info("[worker] 获取到待执行任务 task_id=%s", job_seek_task.id)
        execution = asyncio.create_task(self.executor.execute(job_seek_task))
        stop_waiter = asyncio.create_task(self._stop_event.wait())
        self._active_execution = execution
        self._active_job_seek_task_id = job_seek_task.id

        try:
            while True:
                done, _ = await asyncio.wait(
                    {execution, stop_waiter},
                    timeout=self.control_poll_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if execution in done:
                    try:
                        await execution
                    except asyncio.CancelledError:
                        current = self.repository.get(job_seek_task.id)
                        if current is not None and current.status == JobSeekTaskStatus.RUNNING:
                            self.repository.set_status_if_current(
                                job_seek_task.id,
                                JobSeekTaskStatus.RUNNING,
                                JobSeekTaskStatus.STOPPED,
                            )
                        return True

                    self.repository.set_status_if_current(
                        job_seek_task.id,
                        JobSeekTaskStatus.RUNNING,
                        JobSeekTaskStatus.COMPLETED,
                    )
                    logger.info("[worker] 任务执行完成 task_id=%s", job_seek_task.id)
                    return True

                if stop_waiter in done:
                    self.repository.set_status_if_current(
                        job_seek_task.id,
                        JobSeekTaskStatus.RUNNING,
                        JobSeekTaskStatus.STOPPED,
                    )
                    execution.cancel()
                    with suppress(asyncio.CancelledError):
                        await execution
                    return True

                current = self.repository.get(job_seek_task.id)
                if current is None or current.status != JobSeekTaskStatus.RUNNING:
                    execution.cancel()
                    with suppress(asyncio.CancelledError):
                        await execution
                    return True

        except asyncio.CancelledError:
            self.repository.set_status_if_current(
                job_seek_task.id,
                JobSeekTaskStatus.RUNNING,
                JobSeekTaskStatus.STOPPED,
            )
            execution.cancel()
            with suppress(asyncio.CancelledError):
                await execution
            raise
        except Exception as exc:
            logger.exception("[worker] 任务执行失败 task_id=%s", job_seek_task.id)
            self.repository.set_status_if_current(
                job_seek_task.id,
                JobSeekTaskStatus.RUNNING,
                JobSeekTaskStatus.FAILED,
                error=str(exc),
            )
            return True
        finally:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter
            self._active_execution = None
            self._active_job_seek_task_id = None

    async def run_forever(self) -> None:
        if self._running:
            raise RuntimeError("JobSeekWorker 已经在运行。")

        self._running = True
        logger.info("[worker] 执行器已启动")
        self.repository.recover_running_as_stopped()
        try:
            while not self._stop_event.is_set():
                if await self.run_once():
                    continue
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                except TimeoutError:
                    pass
        finally:
            logger.info("[worker] 执行器已停止")
            self._running = False
            self._active_execution = None
            self._active_job_seek_task_id = None
