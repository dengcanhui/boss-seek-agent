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




def _preference_payload(choice: str, met: float) -> dict:
    return {
        "answers": {
            "preference": {
                "choice": choice,
                "probabilities": {
                    "met": met,
                    "unmet": (1 - met) if choice == "unmet" else 0.02,
                    "unknown": (1 - met) if choice == "unknown" else (0.98 - met if choice == "met" else 0.0),
                },
            }
        }
    }


def _profile_with_required(*requirements: str, preferred: list[str] | None = None):
    from app.domain.candidate.models import CandidateProfile, JobPreferences
    return CandidateProfile(
        expected_jobs=["Agent开发"],
        skills=["Python"],
        job_preferences=JobPreferences(required=list(requirements), preferred=preferred or []),
    )


def test_required_job_preference_passes_only_when_explicitly_met():
    from tests.test_ollama_greeting_filter import decision_payload
    model = SimpleNamespace(evaluate=AsyncMock(side_effect=[
        _preference_payload("met", 0.95),
        decision_payload(),
    ]))
    profile = _profile_with_required("必须双休", preferred=["少加班"])
    f = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), model)

    result = asyncio.run(
        f.check_detail(detail_payload("周末双休，使用Python开发Agent"), GlobalConfig())
    )
    assert result.passed
    assert model.evaluate.await_count == 2
    first_request = model.evaluate.call_args_list[0].kwargs
    assert list(first_request["questions"]) == ["preference"]
    assert "必须双休" in first_request["questions"]["preference"]["instructions"]
    assert "周末双休" in first_request["state"]["job"]["description"]


def test_required_job_preference_rejects_unmet_unknown_and_low_confidence():
    for choice, met_prob in [
        ("unmet", 0.02),
        ("unknown", 0.02),
        ("met", 0.53),
    ]:
        model = SimpleNamespace(evaluate=AsyncMock(return_value=_preference_payload(choice, met_prob)))
        f = BossJobFilter(
            SimpleNamespace(get_profile=lambda: _profile_with_required("必须双休")),
            model,
        )
        result = asyncio.run(f.check_detail(detail_payload("未说明休息安排"), GlobalConfig()))
        assert not result.passed
        assert "必须双休" in result.reason
        assert model.evaluate.await_count == 1  # 未通过偏好时不继续技能模型


def test_disabling_model_does_not_silently_ignore_required_preferences():
    model = SimpleNamespace(evaluate=AsyncMock())
    profile = _profile_with_required("不接受出差")
    f = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), model)
    result = asyncio.run(
        f.check_detail(detail_payload("Agent开发"), GlobalConfig(ai_greeting_filter_enabled=False))
    )
    assert not result.passed
    assert "尚未核实" in result.reason
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
