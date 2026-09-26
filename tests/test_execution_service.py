import asyncio

from app.application.execution.job_seek_execution_service import JobSeekExecutionService


class FakeWorker:
    def __init__(self):
        self.active_job_seek_task_id: int | None = None
        self.prepare_calls = 0
        self.stop_calls = 0
        self._stop_event = asyncio.Event()

    def prepare_start(self) -> None:
        self.prepare_calls += 1
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self.stop_calls += 1
        self._stop_event.set()

    async def run_forever(self) -> None:
        self.active_job_seek_task_id = 7
        await self._stop_event.wait()
        self.active_job_seek_task_id = None


class StuckWorker(FakeWorker):
    async def run_forever(self) -> None:
        self.active_job_seek_task_id = 9
        try:
            await asyncio.Event().wait()
        finally:
            self.active_job_seek_task_id = None


def test_execution_service_forces_cancel_after_stop_timeout():
    worker = StuckWorker()
    service = JobSeekExecutionService(worker, stop_timeout=0.01)

    async def scenario():
        await service.start()
        stopped = await service.stop()
        assert stopped.active is False
        assert stopped.current_job_seek_task_id is None
        assert worker.stop_calls == 1

    asyncio.run(scenario())


def test_execution_service_manages_worker_lifecycle():
    worker = FakeWorker()
    service = JobSeekExecutionService(worker)

    assert service.get_state().active is False

    async def scenario():
        started = await service.start()
        assert started.active is True
        assert started.current_job_seek_task_id == 7
        assert worker.prepare_calls == 1

        started_again = await service.start()
        assert started_again.active is True
        assert worker.prepare_calls == 1

        stopped = await service.stop()
        assert stopped.active is False
        assert stopped.current_job_seek_task_id is None
        assert worker.stop_calls == 1

        stopped_again = await service.stop()
        assert stopped_again.active is False

        await service.shutdown()

    asyncio.run(scenario())
