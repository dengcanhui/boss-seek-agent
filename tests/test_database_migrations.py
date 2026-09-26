import json
from pathlib import Path

from sqlalchemy import create_engine, text

from app.infrastructure.database.database import (
    Base,
    _migrate_search_task_config_names,
    _migrate_unlimited_search_values,
)
from app.infrastructure.database import tables  # noqa: F401


def test_search_task_migrations_normalize_old_config(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)

    old_config = {
        "keyword": "Agent",
        "city": "101210100",
        "job_type": "0",
        "salary": "0",
        "experiences": ["0", "104"],
        "degrees": ["203"],
        "industries": [],
        "scales": [],
        "stages": [],
    }

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO search_tasks(config_json, priority, status, created_at, updated_at) "
                "VALUES (:config_json, 0, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"config_json": json.dumps(old_config)},
        )
        _migrate_search_task_config_names(connection)
        _migrate_unlimited_search_values(connection)
        raw = connection.scalar(text("SELECT config_json FROM search_tasks LIMIT 1"))

    data = json.loads(raw)
    assert data == {
        "query": "Agent",
        "city": "101210100",
        "jobType": None,
        "salary": None,
        "experience": ["104"],
        "degree": ["203"],
        "industry": [],
        "scale": [],
        "stage": [],
    }
