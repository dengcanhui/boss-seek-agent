import asyncio

from app.agent.tools.registry import ToolRegistry
from app.application.search.boss_search_options import BossSearchOptionsService
from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.job_seek_task_service import JobSeekTaskService


def test_semantic_guide_contains_small_enums_only():
    service = BossSearchOptionsService()
    guide = service.semantic_guide()

    assert guide["allowed_values"]["jobType"] == ["全职", "兼职"]
    assert "10-20K" in guide["allowed_values"]["salary"]
    assert "经验不限" in guide["allowed_values"]["experience"]
    assert "本科" in guide["allowed_values"]["degree"]
    assert "city" not in guide["allowed_values"]
    assert "industry" not in guide["allowed_values"]


def test_search_city_returns_semantic_name_without_code():
    service = BossSearchOptionsService()

    results = service.search_options("city", "杭州市")

    assert results[0] == {"name": "杭州"}
    assert all("code" not in result for result in results)


def test_search_industry_supports_exact_name_and_group_keyword():
    service = BossSearchOptionsService()

    exact = service.search_options("industry", "人工智能行业")
    group = service.search_options("industry", "AI", limit=20)

    assert exact[0]["name"] == "人工智能"
    assert exact[0]["group"] == "互联网/AI"
    assert any(result["name"] == "人工智能" for result in group)
    assert all("code" not in result for result in exact + group)


def test_search_options_tool_schema_limits_field_to_city_or_industry():
    registry = ToolRegistry()
    registry.register_service(BossSearchOptionsService())

    schema = next(
        item["function"]
        for item in registry.schemas()
        if item["function"]["name"] == "search_boss_options"
    )

    assert schema["parameters"]["properties"]["field"]["enum"] == ["city", "industry"]
    results = asyncio.run(
        registry.execute(
            "search_boss_options",
            {"field": "industry", "keyword": "人工智能", "limit": 5},
        )
    )
    assert results[0]["name"] == "人工智能"


def test_task_tool_schema_explains_semantic_parameter_rules():
    options_service = BossSearchOptionsService()
    task_service = JobSeekTaskService(
        object(),
        BossSearchConfigCompiler(options_service.options),
    )
    registry = ToolRegistry()
    registry.register_service(task_service)

    schema = next(
        item["function"]["parameters"]
        for item in registry.schemas()
        if item["function"]["name"] == "create_task"
    )
    params_schema = schema["$defs"]["JobSeekTaskParams"]["properties"]

    assert "search_boss_options" in params_schema["city"]["description"]
    assert "allowed_values.salary" in params_schema["salary"]["description"]
    assert "细分行业" in params_schema["industry"]["description"]
