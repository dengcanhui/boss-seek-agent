from fastapi import APIRouter

from app.api.dependencies import GlobalConfigServiceDep
from app.domain.global_config import GlobalConfig, GlobalConfigUpdate

router = APIRouter(prefix="/global-config", tags=["global-config"])


@router.get("", response_model=GlobalConfig)
def get_global_config(service: GlobalConfigServiceDep):
    return service.get()


@router.patch("", response_model=GlobalConfig)
def update_global_config(changes: GlobalConfigUpdate, service: GlobalConfigServiceDep):
    return service.update(changes)
