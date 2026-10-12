import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.domain.global_config import GlobalConfig
from app.execution.boss.executor import BossJobExecutor
from app.execution.filters.boss import BossJobFilter
from tests.test_browser import FakeBrowser, FakeJobRecords


def detail_payload(description="Python Agent 与 RAG 开发"):
    return {
        "code": 0,
        "zpData": {
            "jobInfo": {
                "jobName": "Agent 开发",
                "postDescription": description,
                "invalidStatus": False,
            },
            "brandComInfo": {"brandName": "示例科技"},
            "bossInfo": {"activeTimeDesc": "刚刚活跃"},
            "relationInfo": {"interestJob": False, "beFriend": False},
        },
    }




def _profile_with_required(*requirements: str, preferred: list[str] | None = None):
    from app.domain.candidate.models import CandidateProfile, JobPreferences
    return CandidateProfile(
        expected_jobs=["Agent开发"],
        skills=["Python"],
        job_preferences=JobPreferences(required=list(requirements), preferred=preferred or []),
    )


def test_missing_rest_or_interview_information_does_not_block():
    from tests.test_ollama_greeting_filter import single_answer
    evaluator = AsyncMock(side_effect=[
        single_answer("core_skill"), single_answer("hard_conflict"),
    ])
    profile = _profile_with_required(
        "不接受单休", "不接受线下面试", preferred=["希望少加班"]
    )
    f = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))

    result = asyncio.run(
        f.check_detail(detail_payload("使用Python开发Agent，负责RAG"), GlobalConfig())
    )
    assert result.passed
    assert evaluator.await_count == 2
    first, second = (call.kwargs for call in evaluator.await_args_list)
    assert first["state"]["candidate"] == {"skills": ["Python"]}
    assert set(first["questions"]) == {"core_skill"}
    assert second["state"]["candidate"] == {
        "required": ["不接受单休", "不接受线下面试"]
    }
    assert "希望少加班" not in str(second["state"])
    assert "面试方式" in second["questions"]["hard_conflict"]["instructions"]


def test_explicit_user_bottom_line_conflicts_are_rejected_in_second_request():
    from tests.test_ollama_greeting_filter import single_answer
    cases = (
        ("明确单休，Python Agent研发", ["不接受单休"]),
        ("必须到现场线下面试，Python Agent研发", ["不接受线下面试"]),
    )
    for description, required in cases:
        evaluator = AsyncMock(side_effect=[
            single_answer("core_skill"),
            single_answer("hard_conflict", choice="conflict", reject_prob=0.96),
        ])
        profile = _profile_with_required(*required)
        profile.degree = "本科"
        profile.experience_years = 3
        filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
        result = asyncio.run(filt.check_detail(detail_payload(description), GlobalConfig()))
        assert not result.passed
        assert "硬性条件：" in result.reason
        assert evaluator.await_count == 2
        request = evaluator.await_args_list[1].kwargs
        assert request["state"]["job"]["description"] == description
        assert request["state"]["candidate"] == {"required": required}


def test_education_and_years_not_used_as_hard_conflicts():
    from tests.test_ollama_greeting_filter import single_answer
    evaluator = AsyncMock(return_value=single_answer("core_skill"))
    profile = _profile_with_required()
    profile.degree = "本科"
    profile.experience_years = 3
    filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_detail(
        detail_payload("学历要求硕士及以上，要求5年以上经验，主要为Python开发"), GlobalConfig()
    ))
    assert result.passed
    evaluator.assert_awaited_once()
    assert "未设置个人底线" in result.reason


def test_disabling_ai_filter_skips_only_model_filter():
    model = SimpleNamespace(evaluate=AsyncMock())
    profile = _profile_with_required("不接受出差")
    f = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), model)
    result = asyncio.run(
        f.check_detail(detail_payload("Agent开发"), GlobalConfig(ai_greeting_filter_enabled=False))
    )
    assert result.passed
    model.evaluate.assert_not_awaited()


def test_soft_preferences_never_block_when_model_filter_disabled():
    profile = _profile_with_required(preferred=["少加班", "可以远程"])
    f = BossJobFilter(SimpleNamespace(get_profile=lambda: profile))
    result = asyncio.run(
        f.check_detail(detail_payload("没有提到加班"), GlobalConfig(ai_greeting_filter_enabled=False))
    )
    assert result.passed

def test_card_filter_checks_title_and_company_text_before_detail():
    f = BossJobFilter()
    assert not f.check_card(
        "Agent 开发 | 外包公司 | 18-22K", GlobalConfig(company_blacklist=["外包公司"])
    ).passed
    assert not f.check_card(
        "Java 开发 | 示例科技", GlobalConfig(job_blacklist=["Java"])
    ).passed
    assert f.check_card(
        "Python 开发 | 示例科技", GlobalConfig(job_blacklist=["Java"])
    ).passed


def test_detail_filters_user_rules_before_ollama():
    evaluator = SimpleNamespace(evaluate=AsyncMock())
    f = BossJobFilter(
        profile_service=SimpleNamespace(get_profile=lambda: None),
        model_client=evaluator,
    )
    config = GlobalConfig(description_blacklist=["驻场"])
    result = asyncio.run(f.check_detail(detail_payload("长期驻场开发"), config))
    assert result.passed is False
    assert "岗位描述命中黑名单" in result.reason
    evaluator.evaluate.assert_not_awaited()


def test_detail_inactive_and_relation_filter_are_preserved():
    f = BossJobFilter()
    detail = detail_payload()
    for active_desc in ("本周活跃", "本周内活跃"):
        detail["zpData"]["bossInfo"]["activeTimeDesc"] = active_desc
        assert f.check_detail_rules(detail, GlobalConfig()).passed

    detail["zpData"]["bossInfo"]["activeTimeDesc"] = "上周活跃"
    result = f.check_detail_rules(detail, GlobalConfig())
    assert not result.passed
    assert "长期不活跃" in result.reason

    detail["zpData"]["bossInfo"]["activeTimeDesc"] = "刚刚活跃"
    detail["zpData"]["relationInfo"]["beFriend"] = True
    result = f.check_detail_rules(detail, GlobalConfig())
    assert not result.passed
    assert "沟通关系" in result.reason


def test_filter_disabled_skips_ollama_and_model_required_when_enabled():
    f = BossJobFilter()
    detail = detail_payload()
    assert asyncio.run(
        f.check_detail(detail, GlobalConfig(ai_greeting_filter_enabled=False))
    ).passed
    result = asyncio.run(f.check_detail(detail, GlobalConfig(ai_greeting_filter_enabled=True)))
    assert not result.passed
    assert "未配置" in result.reason


def test_card_filter_skips_without_opening_detail_or_creating_record():
    browser = FakeBrowser()
    records = FakeJobRecords()
    executor = BossJobExecutor(browser, job_records=records, job_filter=BossJobFilter())
    executor.DETAIL_CLICK_DELAY = (0, 0)
    config = GlobalConfig(company_blacklist=["示例公司"])
    task = SimpleNamespace(id=1, config=SimpleNamespace(query="Agent"))
    asyncio.run(executor._process_card(task, config, browser.cards[0], 0))
    assert not any(action == "click_element" for action, _ in browser.calls)
    assert not records.saved and not records.not_greeted_reasons


def test_all_cards_filtered_is_not_treated_as_detail_loading_failure():
    browser = FakeBrowser()
    executor = BossJobExecutor(
        browser,
        global_config=SimpleNamespace(
            get=lambda: GlobalConfig(
                company_blacklist=["示例公司"],
                max_jobs_per_task=1,
            )
        ),
    )
    executor.DETAIL_CLICK_DELAY = (0, 0)
    task = SimpleNamespace(
        id=1,
        config=SimpleNamespace(
            query="Agent", city="101210100", jobType=None, salary=None,
            experience=[], degree=[], industry=[], scale=[], stage=[],
        ),
    )
    asyncio.run(executor.execute(task))
    assert not any(action == "click_element" for action, _ in browser.calls)
