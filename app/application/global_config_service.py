from app.domain.global_config import GlobalConfig, GlobalConfigUpdate
from app.infrastructure.database.repositories.global_config_repository import GlobalConfigRepository


class GlobalConfigService:
    def __init__(self, repository: GlobalConfigRepository):
        self.repository: GlobalConfigRepository = repository

    def get(self) -> GlobalConfig:
        return self.repository.load()

    def update(self, changes: GlobalConfigUpdate) -> GlobalConfig:
        current = self.repository.load()
        data = current.model_dump()
        for key, value in changes.model_dump(exclude_unset=True).items():
            data[key] = value
        return self.repository.save(GlobalConfig.model_validate(data))
