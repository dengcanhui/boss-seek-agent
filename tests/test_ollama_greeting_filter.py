import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.execution.filters.base import FilterResult
from app.execution.filters.boss import BossJobFilter
from app.domain.candidate.models import CandidateProfile
from app.domain.global_config import GlobalConfig
from app.execution.boss.executor import BossJobExecutor
from app.infrastructure.llm.ollama_decision_client import OllamaDecisionClient
from tests.test_browser import FakeBrowser, FakeJobRecords


class FakeProfileService:
    def get_profile(self):
        return CandidateProfile(
            expected_jobs=["Agent 开发"],
            skills=["Python", "LangChain", "RAG"],
            experience_years=3,
            degree="本科",
        )


def decision_payload(
    *,
    skill_choice="acceptable",
    skill_acceptable=0.68,
    hard_choice="no_proven_conflict",
    hard_conflict=0.01,
):
    return {
        "model": "tev1:4b",
        "answers": {
            "core_skill": {
                "type": "choice",
                "choice": skill_choice,
                "probabilities": {
                    "acceptable": skill_acceptable,
                    "major_gap": 1 - skill_acceptable,
                },
            },
            "hard_conflict": {
                "type": "choice",
                "choice": hard_choice,
                "probabilities": {
                    "conflict": hard_conflict,
                    "no_proven_conflict": 1 - hard_conflict,
                },
            },
        },
    }


def test_model_input_keeps_hard_preferences_but_not_soft_preferences_and_trims_jd():
    description = "岗位职责：" + "A" * 1600 + "任职要求：" + "B" * 1300
    full = {
        "candidate": {
            "expected_jobs": ["Agent开发"],
            "skills": ["Python", "RAG"],
            "experience_years": 3,
            "degree": "本科",
            "job_preferences": {
                "required": ["不接受单休", "不接受线下面试"],
                "preferred": ["希望少加班"],
            },
            "expected_cities": ["杭州"],
            "search_preferences": {"city_tier": "新一线"},
        },
        "search_keyword": "Agent",
        "job": {
            "title": "Agent开发工程师",
            "description": description,
            "company": "测试公司",
            "salary": "20K",
        },
    }
    compact = BossJobFilter.compact_model_state(full)
    assert compact["candidate"] == {
        "expected_jobs": ["Agent开发"],
        "skills": ["Python", "RAG"],
        "experience_years": 3,
        "degree": "本科",
        "job_preferences": {"required": ["不接受单休", "不接受线下面试"]},
    }
    assert set(compact["job"]) == {"title", "description"}
    assert compact["job"]["description"].startswith("岗位职责：")
    assert compact["job"]["description"].endswith("B" * 200)
    assert len(compact["job"]["description"]) < 1900
    assert full["job"]["description"] == description


def test_ollama_decision_allows_related_skill_and_no_proven_conflict():
    result = BossJobFilter.parse_decision(
        decision_payload(skill_acceptable=0.56, hard_conflict=0.013)
    )
    assert result.passed is True
    assert "冲突概率 0.01" in result.reason


def test_ollama_decision_rejects_major_skill_gap_or_clear_hard_conflict():
    gap = BossJobFilter.parse_decision(
        decision_payload(skill_choice="major_gap", skill_acceptable=0.02)
    )
    assert not gap.passed
    assert "核心技术差距过大" in gap.reason

    conflict = BossJobFilter.parse_decision(
        decision_payload(hard_choice="conflict", hard_conflict=0.87)
    )
    assert not conflict.passed
    assert "明确硬性条件冲突" in conflict.reason


def test_ollama_decision_allows_uncertain_conflict_and_partial_technical_fit():
    # 低概率的冲突猜测不构成明确冲突，避免错过合适岗位。
    uncertain = BossJobFilter.parse_decision(
        decision_payload(hard_choice="conflict", hard_conflict=0.51)
    )
    assert uncertain.passed is True
    assert "暂不否决" in uncertain.reason

    # 技术大体可接受时，不再因概率未达到旧阈值而拒绝。
    partial = BossJobFilter.parse_decision(
        decision_payload(skill_acceptable=0.49)
    )
    assert partial.passed is True


def test_ollama_decision_rejects_invalid_answer():
    with pytest.raises(ValueError, match="answers"):
        BossJobFilter.parse_decision({"model": "tev1:4b"})
    with pytest.raises(ValueError, match="core_skill"):
        BossJobFilter.parse_decision(
            {"answers": {"core_skill": {"choice": "match"}}}
        )


def test_job_match_filter_calls_model_and_fails_closed():
    fake_evaluate = AsyncMock(return_value=decision_payload())
    service = BossJobFilter(
        FakeProfileService(),
        SimpleNamespace(evaluate=fake_evaluate),
    )
    detail = {
        "zpData": {
            "jobInfo": {"jobName": "Agent 开发", "postDescription": "熟悉 Python 和 RAG"},
            "brandComInfo": {"brandName": "示例公司"},
        }
    }
    result = asyncio.run(service.check_model(detail, search_keyword="Agent"))
    assert result.passed is True
    kwargs = fake_evaluate.call_args.kwargs
    assert "RAG" in kwargs["state"]["job"]["description"]
    assert "LangChain" in kwargs["state"]["candidate"]["skills"]
    assert set(kwargs["questions"]) == {"core_skill", "hard_conflict"}
    assert kwargs["state"]["candidate"]["job_preferences"]["required"] == []

    fake_evaluate.side_effect = httpx.TimeoutException("server timeout")
    failure = asyncio.run(service.check_model(detail, search_keyword="Agent"))
    assert failure.passed is False
    assert "Ollama" in failure.reason


def test_ollama_client_only_handles_external_http():
    client = OllamaDecisionClient(model="tev1:4b")
    request = httpx.Request("POST", "http://127.0.0.1:11434/v1/systemone")
    fake_post = AsyncMock(
        return_value=httpx.Response(200, json=decision_payload(), request=request)
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
