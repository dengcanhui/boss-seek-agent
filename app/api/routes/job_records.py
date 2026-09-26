from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import JobRecordRepositoryDep
from app.domain.job_record import JobRecord, JobRecordSummary

router = APIRouter(prefix="/job-records", tags=["job-records"])


@router.get("", response_model=list[JobRecordSummary])
def list_job_records(
    repository: JobRecordRepositoryDep,
    limit: int = Query(default=100, ge=1, le=500),
):
    return repository.list(limit=limit)


@router.get("/{record_id}", response_model=JobRecord)
def get_job_record(record_id: int, repository: JobRecordRepositoryDep):
    record = repository.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="岗位记录不存在")
    return record
