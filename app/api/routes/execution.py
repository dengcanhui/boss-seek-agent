from fastapi import APIRouter, HTTPException

from app.api.dependencies import BrowserDep, JobSeekExecutionServiceDep
from app.application.execution.models import JobSeekExecutionState

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("", response_model=JobSeekExecutionState)
def execution_state(service: JobSeekExecutionServiceDep):
    return service.get_state()


@router.post("/start", response_model=JobSeekExecutionState)
async def start_execution(service: JobSeekExecutionServiceDep):
    return await service.start()


@router.post("/stop", response_model=JobSeekExecutionState)
async def stop_execution(service: JobSeekExecutionServiceDep):
    return await service.stop()


@router.post("/browser/open")
async def open_browser_for_manual_login(
    service: JobSeekExecutionServiceDep,
    browser: BrowserDep,
):
    if service.get_state().active:
        raise HTTPException(status_code=409, detail="执行器运行中，请先停止执行器再手动登录。")

    url = await browser.open_for_manual_login()
    return {"status": "opened", "url": url}
