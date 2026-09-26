import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.global_config import GlobalConfig
from app.execution.boss import locators
from app.execution.boss.executor import BossJobExecutor
from app.infrastructure.browser.ruyipage import RuyiPageBrowser


def test_ruyipage_browser_uses_project_local_paths(tmp_path: Path):
    browser = RuyiPageBrowser(
        tmp_path,
        browsers_dir="runtime/browsers",
        profile_dir="runtime/profile",
    )

    assert browser.browsers_dir == (tmp_path / "runtime/browsers").resolve()
    assert browser.profile_dir == (tmp_path / "runtime/profile").resolve()
    assert browser._find_browser() is None


def test_ruyipage_browser_detects_project_firefox(tmp_path: Path):
    browser = RuyiPageBrowser(
        tmp_path,
        browsers_dir="runtime/browsers",
        profile_dir="runtime/profile",
    )

    executable_name = "firefox.exe" if __import__("os").name == "nt" else "firefox"
    executable = browser.browsers_dir / "managed-firefox" / executable_name
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")

    assert browser._find_browser() == executable.resolve()


def test_browser_operations_do_not_auto_start(tmp_path: Path):
    browser = RuyiPageBrowser(tmp_path)

    with pytest.raises(RuntimeError, match="浏览器未启动"):
        asyncio.run(browser.navigate("https://example.com"))


class FakeCard:
    def __init__(self, text: str):
        self.text = text


class FakeJobRecords:
    def __init__(self, *, greeted: bool = False):
        self.greeted = greeted
        self.saved: list[tuple[dict, int | None]] = []
        self.marked: list[dict] = []
        self.not_greeted_reasons: list[str] = []

    def upsert_detail(self, detail, task_id=None):
        self.saved.append((detail, task_id))
        return SimpleNamespace(
            job_key="job-test",
            visit_count=len(self.saved),
            greeted=self.greeted,
        )

    def mark_greeted(self, detail):
        self.greeted = True
        self.marked.append(detail)
        return SimpleNamespace(greeted=True)

    def mark_not_greeted(self, detail, reason):
        self.not_greeted_reasons.append(reason)
        return SimpleNamespace(greeted=False, not_greeted_reason=reason)


class FakeBrowser:
    def __init__(self):
        self.calls: list[tuple[str, str | int | None]] = []
        self.cards = [FakeCard("Agent 开发 | 示例公司")]

    async def start(self):
        self.calls.append(("start", None))

    async def navigate(self, url: str):
        self.calls.append(("navigate", url))

    async def wait_for_element(self, selector: str, *, timeout: float = 10):
        self.calls.append(("wait_for_element", selector))
        return object()

    async def elements(self, selector: str, *, timeout: float = 1):
        self.calls.append(("elements", selector))
        return self.cards

    async def element_text(self, element: FakeCard):
        return element.text

    async def click_element(self, element: FakeCard):
        self.calls.append(("click_element", element.text))

    async def scroll_element_into_view(self, element: FakeCard, *, center: bool = False):
        self.calls.append(("scroll_element_into_view", element.text))

    async def viewport_height(self):
        return 900

    async def element_viewport_box(self, element: FakeCard):
        return {"top": 220.0, "bottom": 360.0, "height": 140.0}

    async def scroll(self, delta_y: int):
        self.calls.append(("scroll", delta_y))

    async def scroll_page(self, delta_y: int):
        self.calls.append(("scroll_page", delta_y))

    async def click(self, selector: str):
        self.calls.append(("click", selector))

    async def click_if_present(self, selector: str, *, timeout: float = 2):
        self.calls.append(("click_if_present", selector))
        return True

    async def capture_json(self, target, action, *, timeout=10):
        await action()
        if "job/detail.json" in target:
            return {
                "code": 0,
                "zpData": {
                    "jobInfo": {"jobName": "Agent 开发", "invalidStatus": False},
                    "relationInfo": {"interestJob": False, "beFriend": False},
                },
            }
        if "joblist.json" in target:
            return {"code": 0, "zpData": {"jobList": []}}
        return None


def test_job_executor_starts_browser_once_before_page_operations():
    browser = FakeBrowser()
    executor = BossJobExecutor(browser)
    executor.MAX_STAGNANT_SCROLLS = 1
    executor.LOAD_MORE_SCROLL_TIMES = (3, 3)
    executor.LOAD_MORE_SCROLL_DELTA = (150, 150)
    executor.LOAD_MORE_SCROLL_PAUSE = (0, 0)
    task = SimpleNamespace(
        config=SimpleNamespace(
            query="Agent",
            city="101210100",
            jobType="0",
            salary="0",
            experience=[],
            degree=[],
            industry=[],
            scale=[],
            stage=[],
        )
    )

    asyncio.run(executor.execute(task))

    assert browser.calls[0] == ("start", None)
    assert browser.calls[1][0] == "navigate"
    assert ("scroll_element_into_view", "Agent 开发 | 示例公司") not in browser.calls
    assert ("click_element", "Agent 开发 | 示例公司") in browser.calls
    assert ("click", ".job-detail-header a.op-btn-chat") in browser.calls
    assert ("click_if_present", locators.GREET_STAY_PAGE) in browser.calls
    scroll_calls = [call for call in browser.calls if call[0] == "scroll_page"]
    assert scroll_calls == [
        ("scroll_page", 150),
        ("scroll_page", 150),
        ("scroll_page", 150),
    ]


def test_job_executor_stops_at_global_max_jobs_per_task():
    class FakeGlobalConfigService:
        def get(self):
            return GlobalConfig(
                max_jobs_per_task=1,
                greet_wait_min_seconds=0,
                greet_wait_max_seconds=0,
            )

    browser = FakeBrowser()
    executor = BossJobExecutor(browser, global_config=FakeGlobalConfigService())
    executor.DETAIL_CLICK_DELAY = (0, 0)
    executor.GREET_CLICK_DELAY = (0, 0)
    executor.DIALOG_CLOSE_DELAY = (0, 0)
    task = SimpleNamespace(
        id=9,
        config=SimpleNamespace(
            query="Agent",
            city="101210100",
            jobType=None,
            salary=None,
            experience=[],
            degree=[],
            industry=[],
            scale=[],
            stage=[],
        ),
    )

    asyncio.run(executor.execute(task))

    assert not [call for call in browser.calls if call[0] == "scroll"]
    assert [call for call in browser.calls if call[0] == "click_element"] == [
        ("click_element", "Agent 开发 | 示例公司")
    ]


def test_job_executor_saves_detail_and_marks_greeted():
    browser = FakeBrowser()
    records = FakeJobRecords()
    executor = BossJobExecutor(browser, job_records=records)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    executor.GREET_CLICK_DELAY = (0, 0)
    executor.DIALOG_CLOSE_DELAY = (0, 0)
    task = SimpleNamespace(id=7)

    asyncio.run(
        executor._process_card(
            task,
            GlobalConfig(greet_wait_min_seconds=0, greet_wait_max_seconds=0),
            browser.cards[0],
            0,
        )
    )

    assert len(records.saved) == 1
    assert records.saved[0][1] == 7
    assert len(records.marked) == 1


def test_job_executor_skips_locally_greeted_job():
    browser = FakeBrowser()
    records = FakeJobRecords(greeted=True)
    executor = BossJobExecutor(browser, job_records=records)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    task = SimpleNamespace(id=8)

    asyncio.run(
        executor._process_card(
            task,
            GlobalConfig(greet_wait_min_seconds=0, greet_wait_max_seconds=0),
            browser.cards[0],
            0,
        )
    )

    assert len(records.saved) == 1
    assert not records.marked
    assert ("click", "a.op-btn.op-btn-chat") not in browser.calls


def test_job_executor_fails_task_when_every_detail_request_fails():
    class DetailFailBrowser(FakeBrowser):
        async def capture_json(self, target, action, *, timeout=10):
            await action()
            if "job/detail.json" in target:
                return None
            return {"code": 0, "zpData": {"jobList": [], "hasMore": False}}

    browser = DetailFailBrowser()
    executor = BossJobExecutor(browser)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    task = SimpleNamespace(
        id=1,
        config=SimpleNamespace(
            query="Agent",
            city="101210100",
            jobType=None,
            salary=None,
            experience=[],
            degree=[],
            industry=[],
            scale=[],
            stage=[],
        ),
    )

    with pytest.raises(RuntimeError, match="没有成功获取任何岗位详情"):
        asyncio.run(executor.execute(task))


def test_job_executor_scrolls_only_when_card_is_outside_reading_area():
    browser = FakeBrowser()

    async def low_card_box(element):
        return {"top": 700.0, "bottom": 840.0, "height": 140.0}

    browser.element_viewport_box = low_card_box
    executor = BossJobExecutor(browser)

    asyncio.run(executor._position_card_for_reading(browser.cards[0]))

    scroll_calls = [call for call in browser.calls if call[0] == "scroll"]
    assert len(scroll_calls) == 1
    assert scroll_calls[0][1] == -138


def test_job_executor_does_not_scroll_back_for_card_near_viewport_top():
    browser = FakeBrowser()

    async def high_card_box(element):
        return {"top": 20.0, "bottom": 160.0, "height": 140.0}

    browser.element_viewport_box = high_card_box
    executor = BossJobExecutor(browser)

    asyncio.run(executor._position_card_for_reading(browser.cards[0]))

    assert not [call for call in browser.calls if call[0] == "scroll"]


def test_job_executor_uses_actual_small_scroll_distance():
    browser = FakeBrowser()

    async def slightly_low_card_box(element):
        return {"top": 572.0, "bottom": 712.0, "height": 140.0}

    browser.element_viewport_box = slightly_low_card_box
    executor = BossJobExecutor(browser)

    asyncio.run(executor._position_card_for_reading(browser.cards[0]))

    scroll_calls = [call for call in browser.calls if call[0] == "scroll"]
    assert scroll_calls == [("scroll", -10)]


def test_job_executor_records_not_greeted_reason():
    browser = FakeBrowser()
    records = FakeJobRecords()
    executor = BossJobExecutor(browser, job_records=records)
    executor.DETAIL_CLICK_DELAY = (0, 0)
    task = SimpleNamespace(id=9)

    asyncio.run(
        executor._process_card(
            task,
            GlobalConfig(
                job_blacklist=["Agent"],
                greet_wait_min_seconds=0,
                greet_wait_max_seconds=0,
            ),
            browser.cards[0],
            0,
        )
    )

    assert records.not_greeted_reasons == ["职位命中黑名单：Agent"]
    assert not records.marked


def test_job_executor_skips_already_contacted_job():
    executor = BossJobExecutor(FakeBrowser())

    assert executor._should_greet(
        {
            "code": 0,
            "zpData": {
                "jobInfo": {"invalidStatus": False, "jobStatusDesc": "招聘中"},
                "relationInfo": {"interestJob": True, "beFriend": False},
            },
        }
    ) is False


def test_job_executor_accepts_open_uncontacted_job():
    executor = BossJobExecutor(FakeBrowser())

    assert executor._should_greet(
        {
            "code": 0,
            "zpData": {
                "jobInfo": {"invalidStatus": False, "jobStatusDesc": "招聘中"},
                "relationInfo": {"interestJob": False, "beFriend": False},
            },
        }
    ) is True
