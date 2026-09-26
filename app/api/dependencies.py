from typing import Annotated

from fastapi import Depends, HTTPException

from app.agent.runtime import AgentRuntime
from app.application.execution.job_seek_execution_service import JobSeekExecutionService
from app.application.global_config_service import GlobalConfigService
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.bootstrap import container
from app.infrastructure.browser.ruyipage import RuyiPageBrowser
from app.infrastructure.database.repositories.job_record_repository import JobRecordRepository


def get_agent() -> AgentRuntime:
    try:
        return container.agent
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_job_seek_task_service() -> JobSeekTaskService:
    return container.job_seek_tasks


def get_job_seek_execution_service() -> JobSeekExecutionService:
    return container.job_seek_execution


def get_global_config_service() -> GlobalConfigService:
    return container.global_config


def get_job_record_repository() -> JobRecordRepository:
    return container.job_record_repository


def get_browser() -> RuyiPageBrowser:
    return container.browser


AgentDep = Annotated[AgentRuntime, Depends(get_agent)]
JobSeekTaskServiceDep = Annotated[JobSeekTaskService, Depends(get_job_seek_task_service)]
JobSeekExecutionServiceDep = Annotated[
    JobSeekExecutionService,
    Depends(get_job_seek_execution_service),
]
GlobalConfigServiceDep = Annotated[
    GlobalConfigService,
    Depends(get_global_config_service),
]
JobRecordRepositoryDep = Annotated[
    JobRecordRepository,
    Depends(get_job_record_repository),
]
BrowserDep = Annotated[RuyiPageBrowser, Depends(get_browser)]
