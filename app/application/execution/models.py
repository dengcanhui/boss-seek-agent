from pydantic import BaseModel


class JobSeekExecutionState(BaseModel):
    """后台求职执行器的当前运行状态。"""

    # 是否正在执行求职任务。
    active: bool
    # 当前正在执行的任务 ID；空闲时为 None。
    current_job_seek_task_id: int | None = None
    # 最近一次执行错误；没有错误时为 None。
    last_error: str | None = None
