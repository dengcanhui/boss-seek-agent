import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.domain.candidate.models import CandidateProfile
from app.domain.global_config import GlobalConfig
from app.execution.filters.base import FilterResult
from app.execution.filters.boss import BossJobFilter
from app.execution.boss.executor import BossJobExecutor
from app.infrastructure.llm.ollama_decision_client import OllamaDecisionClient
from tests.test_browser import FakeBrowser, FakeJobRecords


class FakeProfileService:
    def get_profile(self):
        return CandidateProfile(skills=["Python", "LangChain", "RAG"], experience_years=3, degree="本科")


def single_answer(name, *, choice=None, reject_prob=0.01):
    labels = {
        "core_skill": ("acceptable", "major_gap"),
        "hard_conflict": ("no_proven_conflict", "conflict"),
    }[name]
    return {"answers": {name: {
        "type": "choice", "choice": choice or labels[0],
        "probabilities": {labels[0]: 1 - reject_prob, labels[1]: reject_prob},
    }}}


def sample_detail(description="Python Agent 开发"):
    return {"zpData": {"jobInfo": {"jobName": "Agent 开发", "postDescription": description}}}


def test_skill_only_call_and_skip_hard_when_required_empty():
    evaluator = AsyncMock(return_value=single_answer("core_skill"))
    filt = BossJobFilter(FakeProfileService(), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_model(sample_detail(), search_keyword="Python后端"))
    assert result.passed
    evaluator.assert_awaited_once()
    request = evaluator.call_args.kwargs
    assert request["state"] == {
        "candidate": {"skills": ["Python", "LangChain", "RAG"]},
        "job": {"title": "Agent 开发", "description": "Python Agent 开发"},
    }
    assert list(request["questions"]) == ["core_skill"]


def test_skill_gap_stops_before_hard_check():
    evaluator = AsyncMock(return_value=single_answer("core_skill", choice="major_gap", reject_prob=0.95))
    profile = CandidateProfile(skills=["Python"], job_preferences={"required": ["只接受双休"]})
    filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_model(sample_detail("销售AI产品")))
    assert not result.passed
    evaluator.assert_awaited_once()


def test_required_second_call_isolated_from_skill_experience_and_degree():
    evaluator = AsyncMock(side_effect=[
        single_answer("core_skill"),
        single_answer("hard_conflict"),
    ])
    profile = CandidateProfile(
        skills=["Python"], degree="本科", experience_years=3,
        job_preferences={"required": ["只接受双休", "只接受线上面试"], "preferred": ["希望不加班"]},
    )
    filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_model(sample_detail("Python开发，要求5年以上经验")))
    assert result.passed and evaluator.await_count == 2
    first, second = (call.kwargs for call in evaluator.await_args_list)
    assert first["state"]["candidate"] == {"skills": ["Python"]}
    assert list(first["questions"]) == ["core_skill"]
    assert second["state"] == {
        "candidate": {"required": ["只接受双休", "只接受线上面试"]},
        "job": {"description": "Python开发，要求5年以上经验"},
    }
    assert list(second["questions"]) == ["hard_conflict"]


@pytest.mark.parametrize("prob,expected", [(0.95, False), (0.65, True)])
def test_model_hard_conflict_threshold(prob, expected):
    evaluator = AsyncMock(side_effect=[
        single_answer("core_skill"),
        single_answer("hard_conflict", choice="conflict", reject_prob=prob),
    ])
    profile = CandidateProfile(skills=["Python"], job_preferences={"required": ["不接受出差"]})
    filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_model(sample_detail("Python 后端")))
    assert result.passed is expected


def test_explicit_weekend_conflict_even_if_model_misses_it():
    evaluator = AsyncMock(side_effect=[single_answer("core_skill"), single_answer("hard_conflict")])
    profile = CandidateProfile(skills=["Python"], job_preferences={"required": ["只接受双休"]})
    filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
    result = asyncio.run(filt.check_model(sample_detail("薪资福利：大小休、五险。")))
    assert not result.passed and "大小周/大小休" in result.reason
    assert evaluator.await_count == 2


def test_no_false_positive_for_negated_weekend_or_optional_interview():
    checker = BossJobFilter._explicit_required_conflict
    required = ["只接受双休", "只接受线上面试"]
    assert checker("福利：大小休、五险", required)
    assert checker("公司采用单休制度", required)
    assert checker("面试要求线下", required)
    assert checker("福利：双休，不实行大小周", required) is None
    assert checker("面试方式：线上或线下均可", required) is None
    assert checker("硕士学历，5年以上经验", required) is None


def test_missing_second_answer_or_model_failure_rejects():
    profile = CandidateProfile(skills=["Python"], job_preferences={"required": ["只接受双休"]})
    for second in ({"answers": {}}, httpx.TimeoutException("timed out")):
        evaluator = AsyncMock(side_effect=[single_answer("core_skill"), second])
        filt = BossJobFilter(SimpleNamespace(get_profile=lambda: profile), SimpleNamespace(evaluate=evaluator))
        result = asyncio.run(filt.check_model(sample_detail()))
        assert not result.passed
        assert "Ollama" in result.reason


def test_invalid_first_answer_rejects_without_second_call():
    evaluator = AsyncMock(return_value={"answers": {"core_skill": {"choice": "what"}}})
    filt = BossJobFilter(FakeProfileService(), SimpleNamespace(evaluate=evaluator))
    assert not asyncio.run(filt.check_model(sample_detail())).passed
    evaluator.assert_awaited_once()


def test_ollama_client_only_handles_external_http():
    client = OllamaDecisionClient(model="tev1:4b")
    request = httpx.Request("POST", "http://127.0.0.1:11434/v1/systemone")
    fake_post = AsyncMock(
        return_value=httpx.Response(200, json=single_answer("core_skill"), request=request)
    )
    original_http_client = client.client
    client.client = SimpleNamespace(post=fake_post)

    async def scenario():
        result = await client.evaluate(
            state={"candidate": {"skills": ["Python"]}},
            questions={"core_skill": {"type": "choice"}},
        )
        assert result["answers"]["core_skill"]["choice"] == "acceptable"
        fake_post.assert_awaited_once_with(
            "/v1/systemone",
            json={
                "model": "tev1:4b",
                "state": {"candidate": {"skills": ["Python"]}},
                "questions": {"core_skill": {"type": "choice"}},
            },
        )
        await original_http_client.aclose()

    asyncio.run(scenario())


def test_executor_skips_when_ollama_rejects_and_records_reason():
    browser = FakeBrowser()
    records = FakeJobRecords()

    class FakeBossJobFilter:
        def __init__(self):
            self.calls = 0

        def check_card(self, text, config):
            return FilterResult.allow()

        async def check_detail(self, detail, config, *, search_keyword=""):
            self.calls += 1
            assert search_keyword == "Agent"
            return FilterResult.reject("AI 过滤：岗位技术栈不匹配")

    ai = FakeBossJobFilter()
    executor = BossJobExecutor(browser, job_records=records, job_filter=ai)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    task = SimpleNamespace(id=42, config=SimpleNamespace(query="Agent"))
    config = GlobalConfig(greet_wait_min_seconds=0, greet_wait_max_seconds=0)

    asyncio.run(executor._process_card(task, config, browser.cards[0], 0))

    assert ai.calls == 1
    assert records.not_greeted_reasons == ["AI 过滤：岗位技术栈不匹配"]
    assert not records.marked
    assert not [call for call in browser.calls if call[0] == "click"]


def test_executor_does_not_call_ollama_if_card_rule_rejects():
    browser = FakeBrowser()
    records = FakeJobRecords()
    evaluator = AsyncMock()
    job_filter = BossJobFilter(FakeProfileService(), SimpleNamespace(evaluate=evaluator))
    executor = BossJobExecutor(browser, job_records=records, job_filter=job_filter)
    executor.DETAIL_CLICK_DELAY = (0, 0)

    asyncio.run(
        executor._process_card(
            SimpleNamespace(id=43, config=SimpleNamespace(query="Agent")),
            GlobalConfig(job_blacklist=["Agent"], greet_wait_min_seconds=0, greet_wait_max_seconds=0),
            browser.cards[0],
            0,
        )
    )
    evaluator.assert_not_awaited()
    assert not records.saved  # 卡片阶段无详情，不创建伪造的岗位历史记录
    assert not [call for call in browser.calls if call[0] == "click_element"]


def test_executor_bypasses_ai_filter_when_disabled():
    browser = FakeBrowser()
    records = FakeJobRecords()
    evaluator = AsyncMock()
    job_filter = BossJobFilter(FakeProfileService(), SimpleNamespace(evaluate=evaluator))
    executor = BossJobExecutor(browser, job_records=records, job_filter=job_filter)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    executor.GREET_CLICK_DELAY = (0, 0)
    executor.DIALOG_CLOSE_DELAY = (0, 0)
    asyncio.run(
        executor._process_card(
            SimpleNamespace(id=44, config=SimpleNamespace(query="Agent")),
            GlobalConfig(
                ai_greeting_filter_enabled=False,
                greet_wait_min_seconds=0,
                greet_wait_max_seconds=0,
            ),
            browser.cards[0],
            0,
        )
    )
    evaluator.assert_not_awaited()
    assert len(records.marked) == 1
