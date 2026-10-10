import asyncio

from app.agent.tools.registry import ToolRegistry
from app.application.search.boss_search_options import BossSearchOptionsService
from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.job_seek_task_service import JobSeekTaskService


def _enum_from_schema(property_schema: dict) -> list[str]:
    """Schema 中允许 None 的单选和多选取其字符串枚举。"""
    variants = property_schema.get("anyOf", [property_schema])
    for variant in variants:
        if "enum" in variant:
            return variant["enum"]
        if "items" in variant and "enum" in variant["items"]:
            return variant["items"]["enum"]
    raise AssertionError(f"没有合法的枚举选项：{property_schema}")


def test_task_param_schema_enumerations_match_boss_options():
    from app.domain.search.models import JobSeekTaskParams

    options = BossSearchOptionsService().options
    schema = JobSeekTaskParams.model_json_schema()["properties"]
    for field in ("jobType", "salary", "experience", "degree", "scale", "stage"):
        assert _enum_from_schema(schema[field]) == list(options[field])
        assert "description" in schema[field]

    # 两个大字段继续使用按需查询工具，不展开所有城市/细分行业选项。
    assert "enum" not in schema["city"]
    assert "enum" not in schema["industry"]


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
    assert _enum_from_schema(params_schema["salary"]) == list(options_service.options["salary"])
    assert "细分行业" in params_schema["industry"]["description"]
    assert _enum_from_schema(params_schema["experience"]) == list(options_service.options["experience"])
    assert _enum_from_schema(params_schema["jobType"]) == list(options_service.options["jobType"])

    # 修改任务的 changes 也必须暴露同一份枚举约束。
    update_schema = next(
        item["function"]["parameters"]
        for item in registry.schemas()
        if item["function"]["name"] == "update_task"
    )
    update_params = update_schema["$defs"]["JobSeekTaskParams"]["properties"]
    assert _enum_from_schema(update_params["salary"]) == list(options_service.options["salary"])
    assert _enum_from_schema(update_params["stage"]) == list(options_service.options["stage"])
