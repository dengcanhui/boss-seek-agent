from sqlalchemy.orm import Session, sessionmaker

from app.domain.global_config import GlobalConfig
from app.infrastructure.database.tables import GlobalConfigRow


class GlobalConfigRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory: sessionmaker[Session] = session_factory

    def load(self) -> GlobalConfig:
        with self.session_factory() as session:
            row = session.get(GlobalConfigRow, 1)
            if row is None:
                config = GlobalConfig()
                row = GlobalConfigRow(id=1, config_json=config.model_dump_json())
                session.add(row)
                session.commit()
                return config
            return GlobalConfig.model_validate_json(row.config_json)

    def save(self, config: GlobalConfig) -> GlobalConfig:
        with self.session_factory() as session:
            row = session.get(GlobalConfigRow, 1)
            if row is None:
                row = GlobalConfigRow(id=1, config_json=config.model_dump_json())
                session.add(row)
            else:
                row.config_json = config.model_dump_json()
            session.commit()
            return config
