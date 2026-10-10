import asyncio

from app.agent.tools.registry import ToolRegistry
from app.application.candidate.candidate_profile_service import CandidateProfileService
from app.domain.candidate.models import CandidateProfile, JobPreferences


class InMemoryProfileRepository:
    def __init__(self, profile=None):
        self.profile = profile or CandidateProfile()

    def load(self):
        return self.profile

    def save(self, profile):
        self.profile = profile
        return profile


def test_update_profile_tool_schema_describes_fields_to_llm():
    registry = ToolRegistry()
    registry.register_service(CandidateProfileService(InMemoryProfileRepository()))
    tool = next(x["function"] for x in registry.schemas() if x["function"]["name"] == "update_profile")
    schema = tool["parameters"]
    profile = schema["$defs"]["CandidateProfile"]
    preferences = schema["$defs"]["JobPreferences"]

    assert "增量更新" in tool["description"]
    assert "必须双休" in profile["properties"]["job_preferences"]["description"]
    assert "搜索" in profile["properties"]["search_preferences"]["description"]
    assert "已有技能" in profile["properties"]["skills"]["description"]
    assert "必须" in preferences["properties"]["required"]["description"]
    assert "非强制" in preferences["properties"]["preferred"]["description"]


def test_job_preferences_can_update_nested_fields_independently_and_clear():
    repository = InMemoryProfileRepository(
        CandidateProfile(
            expected_jobs=["Agent开发"],
            search_preferences={"job_type": "全职"},
            job_preferences=JobPreferences(
                required=["必须双休"],
                preferred=["最好少加班"],
            ),
        )
    )
    service = CandidateProfileService(repository)

    updated = service.update_profile(
        CandidateProfile(job_preferences=JobPreferences(required=["必须双休", "不出差"]))
    )
    assert isinstance(updated.job_preferences, JobPreferences)
    assert updated.job_preferences.required == ["必须双休", "不出差"]
    assert updated.job_preferences.preferred == ["最好少加班"]
    assert updated.expected_jobs == ["Agent开发"]
    assert updated.search_preferences == {"job_type": "全职"}

    updated = service.update_profile(
        CandidateProfile(job_preferences=JobPreferences(preferred=["优先远程办公"]))
    )
    assert updated.job_preferences.required == ["必须双休", "不出差"]
    assert updated.job_preferences.preferred == ["优先远程办公"]

    updated = service.update_profile(
        CandidateProfile(job_preferences=JobPreferences(required=[]))
    )
    assert updated.job_preferences.required == []
    assert updated.job_preferences.preferred == ["优先远程办公"]

    updated = service.update_profile(CandidateProfile.model_validate({"job_preferences": {}}))
    assert updated.job_preferences == JobPreferences()



def test_existing_profile_json_without_new_field_survives_sqlite_roundtrip(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.infrastructure.database.database import Base
    from app.infrastructure.database.repositories.profile_repository import CandidateProfileRepository
    from app.infrastructure.database.tables import CandidateProfileRow

    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    # 模拟已有数据库里不包含新字段的历史 JSON。
    with factory() as session:
        session.add(CandidateProfileRow(
            id=1,
            profile_json='{"expected_jobs":["Agent开发"],"skills":["Python"],"expected_cities":["杭州"]}',
        ))
        session.commit()

    repository = CandidateProfileRepository(factory)
    service = CandidateProfileService(repository)
    assert service.get_profile().job_preferences == JobPreferences()

    service.update_profile(CandidateProfile(
        job_preferences=JobPreferences(required=["必须双休"], preferred=["少加班"]),
    ))
    restored = CandidateProfileRepository(factory).load()
    assert restored.expected_jobs == ["Agent开发"]
    assert restored.skills == ["Python"]
    assert restored.expected_cities == ["杭州"]
    assert restored.job_preferences.required == ["必须双休"]
    assert restored.job_preferences.preferred == ["少加班"]

    service.update_profile(CandidateProfile(job_preferences=JobPreferences(required=[])))
    restored = CandidateProfileRepository(factory).load()
    assert restored.job_preferences.required == []
    assert restored.job_preferences.preferred == ["少加班"]

def test_tool_call_update_preferences_without_other_fields():
    repository = InMemoryProfileRepository(CandidateProfile(
        expected_jobs=["Python后端"],
        job_preferences=JobPreferences(required=["不接受大小周"], preferred=["加班少"]),
    ))
    registry = ToolRegistry()
    registry.register_service(CandidateProfileService(repository))
    result = asyncio.run(registry.execute("update_profile", {
        "changes": {"job_preferences": {"required": ["必须双休"]}}
    }))

    assert result.job_preferences.required == ["必须双休"]
    assert result.job_preferences.preferred == ["加班少"]
    assert result.expected_jobs == ["Python后端"]
