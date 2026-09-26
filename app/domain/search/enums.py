from enum import StrEnum


class JobSeekTaskStatus(StrEnum):
    """求职任务生命周期状态。"""

    # 等待后台 Worker 执行。
    PENDING = "pending"
    # 正在执行。
    RUNNING = "running"
    # 正常执行完成。
    COMPLETED = "completed"
    # 执行失败。
    FAILED = "failed"
    # 用户或系统主动停止。
    STOPPED = "stopped"
    # 在执行前被取消。
    CANCELLED = "cancelled"
