from app.agent.tools.decorator import agent_tool
from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import JobSeekTask, JobSeekTaskParams
from app.infrastructure.database.repositories.job_seek_task_repository import JobSeekTaskRepository

from .boss_search_config_compiler import BossSearchConfigCompiler


class JobSeekTaskService:
    def __init__(
        self,
        repository: JobSeekTaskRepository,
        compiler: BossSearchConfigCompiler,
    ):
        self.repository: JobSeekTaskRepository = repository
        self.compiler: BossSearchConfigCompiler = compiler

    @agent_tool(description="列出求职任务，可按状态筛选，用于查询任务 ID、优先级和状态。")
    def list_tasks(
        self,
        limit: int = 100,
        statuses: list[JobSeekTaskStatus] | None = None,
    ) -> list[JobSeekTask]:
        return self.repository.list(statuses=statuses, limit=limit)

    def list_active_tasks(self, limit: int = 50) -> list[JobSeekTask]:
        return self.repository.list(
            statuses=[JobSeekTaskStatus.PENDING, JobSeekTaskStatus.RUNNING],
            limit=limit,
        )

    def get_task(self, task_id: int) -> JobSeekTask | None:
        return self.repository.get(task_id)

    def get_options(self) -> dict[str, dict[str, str]]:
        """返回 UI 创建/编辑求职任务时使用的 BOSS 人类语义选项。"""
        return self.compiler.options

    @agent_tool(description="创建一个新的求职任务。城市和关键词必须明确。")
    def create_task(self, params: JobSeekTaskParams) -> JobSeekTask:
        config = self.compiler.compile(params)
        priority = 0 if params.priority is None else params.priority
        return self.repository.create(config, priority)

    @agent_tool(description="修改一个待执行求职任务。运行中的任务不能直接修改。")
    def update_task(self, task_id: int, changes: JobSeekTaskParams) -> JobSeekTask:
        task = self._require(task_id)
        if task.status != JobSeekTaskStatus.PENDING:
            raise ValueError("只有 pending 状态任务允许修改。")
        config = self.compiler.compile_update(task.config, changes)
        priority = changes.priority if changes.priority is not None else task.priority
        updated = self.repository.update_if_current(
            task_id,
            JobSeekTaskStatus.PENDING,
            config=config,
            priority=priority,
        )
        if updated.status != JobSeekTaskStatus.PENDING:
            raise ValueError("任务状态已发生变化，请刷新后重试。")
        return updated

    @agent_tool(description="取消一个未结束的求职任务。")
    def cancel_task(self, task_id: int) -> JobSeekTask:
        for _ in range(4):
            task = self._require(task_id)
            if task.status == JobSeekTaskStatus.CANCELLED:
                return task
            if task.status in {JobSeekTaskStatus.PENDING, JobSeekTaskStatus.RUNNING}:
                updated = self.repository.set_status_if_current(
                    task_id,
                    task.status,
                    JobSeekTaskStatus.CANCELLED,
                )
                if updated.status == JobSeekTaskStatus.CANCELLED:
                    return updated
                continue
            raise ValueError("已结束或已停止的任务不能取消。")
        raise ValueError("任务状态持续变化，请稍后重试。")

    @agent_tool(description="调整待执行求职任务的优先级，数字越小越优先。")
    def set_priority(self, task_id: int, priority: int) -> JobSeekTask:
        task = self._require(task_id)
        if task.status != JobSeekTaskStatus.PENDING:
            raise ValueError("只有 pending 状态任务允许调整优先级。")
        updated = self.repository.update_if_current(
            task_id,
            JobSeekTaskStatus.PENDING,
            priority=priority,
        )
        if updated.status != JobSeekTaskStatus.PENDING:
            raise ValueError("任务状态已发生变化，请刷新后重试。")
        return updated

    @agent_tool(description="把 completed、failed、cancelled 或 stopped 任务复制为新的 pending 任务。")
    def requeue_task(self, task_id: int, priority: int | None = None) -> JobSeekTask:
        task = self._require(task_id)
        terminal = {
            JobSeekTaskStatus.COMPLETED,
            JobSeekTaskStatus.FAILED,
            JobSeekTaskStatus.CANCELLED,
            JobSeekTaskStatus.STOPPED,
        }
        if task.status not in terminal:
            raise ValueError("只有已结束、已取消或已停止的任务允许重新入队。")
        return self.repository.create(task.config, task.priority if priority is None else priority)

    def delete_task(self, task_id: int) -> None:
        task = self._require(task_id)
        if task.status != JobSeekTaskStatus.PENDING:
            raise ValueError("只有 pending 状态任务允许删除；已执行任务属于历史记录，不能修改或删除。")
        if not self.repository.delete_if_current(task_id, JobSeekTaskStatus.PENDING):
            raise ValueError("任务状态已发生变化，请刷新后重试。")

    def _require(self, task_id: int) -> JobSeekTask:
        task = self.repository.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在: {task_id}")
        return task
