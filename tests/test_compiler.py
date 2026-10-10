import pytest
from pydantic import ValidationError

from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.boss_search_options import load_boss_options
from app.domain.search.models import BossSearchConfig, JobSeekTaskParams


def test_small_boss_options_are_validated_by_pydantic():
    with pytest.raises(ValidationError, match="salary"):
        JobSeekTaskParams(salary="15-25K")

    with pytest.raises(ValidationError, match="experience"):
        JobSeekTaskParams(experience=["1-3年", "虚构经验"])

    with pytest.raises(ValidationError, match="jobType"):
        JobSeekTaskParams(jobType="1901")

    # 城市和行业仍是语义名称，由 Compiler 和选项表做合法性校验。
    params = JobSeekTaskParams(
        jobType="全职", salary="10-20K",
        experience=["1-3年", "3-5年"], degree=["本科", "硕士"],
        scale=["100-499人"], stage=["未融资"],
    )
    assert params.model_dump(exclude_none=True)["salary"] == "10-20K"


def test_compile_human_values():
    compiler = BossSearchConfigCompiler()
    result = compiler.compile(
        JobSeekTaskParams(
            query="Agent",
            city="杭州",
            salary="10-20K",
            degree=["本科"],
        )
    )
    assert result.query == "Agent"
    assert result.city == "101210100"
    assert result.salary == "405"
    assert result.degree == ["203"]


def test_optional_request_fields_default_to_none():
    config = BossSearchConfig(query="Agent", city="101210100")
    assert config.jobType is None
    assert config.salary is None


def test_compile_rejects_missing_required_create_fields():
    compiler = BossSearchConfigCompiler()

    with pytest.raises(ValueError, match="query 不能为空"):
        compiler.compile(JobSeekTaskParams(city="杭州"))
    with pytest.raises(ValueError, match="city 不能为空"):
        compiler.compile(JobSeekTaskParams(query="Agent"))


def test_compile_unlimited_single_fields_as_none():
    compiler = BossSearchConfigCompiler()
    result = compiler.compile(
        JobSeekTaskParams(
            query="Agent",
            city="杭州",
            jobType="不限",
            salary="不限",
        )
    )

    assert result.jobType is None
    assert result.salary is None


def test_compile_rejects_raw_boss_code_from_semantic_params():
    compiler = BossSearchConfigCompiler()

    with pytest.raises(ValueError, match="未知 city"):
        compiler.compile(JobSeekTaskParams(query="Agent", city="101210100"))


def test_compile_update_preserves_omitted_fields_and_can_clear_optional_fields():
    compiler = BossSearchConfigCompiler()
    current = compiler.compile(
        JobSeekTaskParams(
            query="Agent",
            city="杭州",
            jobType="全职",
            salary="10-20K",
            degree=["本科"],
        )
    )

    updated = compiler.compile_update(
        current,
        JobSeekTaskParams(salary=None, degree=[]),
    )

    assert updated.query == "Agent"
    assert updated.city == "101210100"
    assert updated.jobType == "1901"
    assert updated.salary is None
    assert updated.degree == []


def test_compile_industry_from_options_file():
    compiler = BossSearchConfigCompiler()

    result = compiler.compile(
        JobSeekTaskParams(
            query="Agent",
            city="杭州",
            industry=["互联网", "人工智能"],
        )
    )

    assert result.industry == ["100020", "100028"]


def test_load_boss_options_uses_complete_data_file():
    options = load_boss_options()

    assert len(options["city"]) == 374
    assert len(options["industry"]) == 146
    assert options["city"]["北京"] == "101010100"
    assert options["city"]["杭州"] == "101210100"
    assert options["industry"]["互联网"] == "100020"
    assert options["industry"]["人工智能"] == "100028"


def test_boss_search_config_fields_match_browser_request_parameters():
    assert set(BossSearchConfig.model_fields) == {
        "query",
        "city",
        "jobType",
        "salary",
        "experience",
        "degree",
        "industry",
        "scale",
        "stage",
    }
