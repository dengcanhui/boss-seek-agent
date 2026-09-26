from fastapi import APIRouter, HTTPException, Query, Response

from app.api.dependencies import JobSeekTaskServiceDep
from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import JobSeekTask, JobSeekTaskParams

router = APIRouter(prefix="/job-seek-tasks", tags=["job-seek-tasks"])


@router.get("", response_model=list[JobSeekTask])
def list_tasks(
    service: JobSeekTaskServiceDep,
    limit: int = Query(default=100, ge=1, le=500),
    statuses: list[JobSeekTaskStatus] | None = Query(default=None),
):
    return service.list_tasks(limit, statuses)


@router.get("/options")
def get_options(service: JobSeekTaskServiceDep):
    return service.get_options()


@router.post("", response_model=JobSeekTask)
def create_task(params: JobSeekTaskParams, service: JobSeekTaskServiceDep):
    try:
        return service.create_task(params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/{task_id}", response_model=JobSeekTask)
def update_task(task_id: int, changes: JobSeekTaskParams, service: JobSeekTaskServiceDep):
    try:
        return service.update_task(task_id, changes)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/cancel", response_model=JobSeekTask)
def cancel_task(task_id: int, service: JobSeekTaskServiceDep):
    try:
        return service.cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/requeue", response_model=JobSeekTask)
def requeue_task(
    task_id: int,
    service: JobSeekTaskServiceDep,
    priority: int | None = None,
):
    try:
        return service.requeue_task(task_id, priority)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, service: JobSeekTaskServiceDep):
    try:
        service.delete_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)
