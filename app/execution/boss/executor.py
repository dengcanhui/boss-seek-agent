from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.application.global_config_service import GlobalConfigService
from app.domain.global_config import GlobalConfig
from app.domain.search.models import JobSeekTask
from app.infrastructure.browser.ruyipage import RuyiPageBrowser
from app.infrastructure.database.repositories.job_record_repository import JobRecordRepository

from . import locators

logger = logging.getLogger("uvicorn.error.boss")


@dataclass
class JobWalkStats:
    """单次岗位遍历过程中的执行统计。"""

    # 已读取过的岗位卡片数量。
    visited: int = 0
    # 成功加载岗位详情的数量。
    detail_loaded: int = 0
    # 已完成完整处理流程的岗位数量。
    handled: int = 0
    # 因过滤规则或状态判断被跳过的岗位数量。
    skipped: int = 0
    # 成功执行打招呼动作的岗位数量。
    greeted: int = 0
    # 处理过程中发生异常的岗位数量。
    errors: int = 0


class BossJobExecutor:
    """执行一条完整 BOSS 求职任务。

    执行顺序固定为：
    搜索页加载 -> 逐个读取岗位卡片 -> 将当前岗位滚入视野 -> 卡片级过滤 ->
    点击岗位并等待详情接口 -> 详情判断 -> 打招呼 -> 小幅下滚 -> 处理下一个岗位。
    只有走到当前已加载列表尾部时，才额外等待下一批岗位加载。

    页面结构相关内容统一放在 ``locators.py``。详情数据优先读取 BOSS 自己的
    ``job/detail.json`` 响应，不依赖详情区 DOM 文本。
    """

    LIST_TIMEOUT = 15.0
    DETAIL_TIMEOUT = 8.0
    GREET_DIALOG_TIMEOUT = 2.0
    LOAD_MORE_TIMEOUT = 5.0
    MAX_STAGNANT_SCROLLS = 5
    CARD_READ_BOTTOM_RATIO = 0.78
    CARD_SCROLL_MAX = 240
    LOAD_MORE_SCROLL_TIMES = (3, 6)
    LOAD_MORE_SCROLL_DELTA = (80, 150)
    LOAD_MORE_SCROLL_PAUSE = (0.12, 0.35)

    # 页面交互前增加轻微随机停顿，避免详情、打招呼、关闭弹窗连续瞬时触发。
    DETAIL_CLICK_DELAY = (1.1, 1.8)
    GREET_CLICK_DELAY = (1, 1.8)
    DIALOG_CLOSE_DELAY = (0.5, 1.2)

    def __init__(
        self,
        browser: RuyiPageBrowser,
        global_config: GlobalConfigService | None = None,
        job_records: JobRecordRepository | None = None,
    ):
        self.browser: RuyiPageBrowser = browser
        self.global_config: GlobalConfigService | None = global_config
        self.job_records: JobRecordRepository | None = job_records

    def build_search_url(self, job_seek_task: JobSeekTask) -> str:
        config = job_seek_task.config
        params = {
            "query": config.query,
            "city": config.city,
            "jobType": config.jobType,
            "salary": config.salary,
            "experience": ",".join(config.experience),
            "degree": ",".join(config.degree),
            "industry": ",".join(config.industry),
            "scale": ",".join(config.scale),
            "stage": ",".join(config.stage),
        }
        return "https://www.zhipin.com/web/geek/job?" + urlencode(
            {key: value for key, value in params.items() if value}
        )

    async def execute(self, job_seek_task: JobSeekTask) -> None:
        """执行一条搜索任务，直到列表不再产生新岗位。"""
        task_id = getattr(job_seek_task, "id", "?")
        logger.info(
            "[boss] 开始执行任务 id=%s query=%s city=%s",
            task_id,
            job_seek_task.config.query,
            job_seek_task.config.city,
        )
        config = (
            self.global_config.get()
            if self.global_config is not None
            else GlobalConfig(greet_wait_min_seconds=0, greet_wait_max_seconds=0)
        )
        logger.info(
            "[boss] 已加载全局配置 company_blacklist=%s job_blacklist=%s description_blacklist=%s inactive_filter=%s max_jobs=%s greet_wait=%.1f~%.1fs",
            len(config.company_blacklist),
            len(config.job_blacklist),
            len(config.description_blacklist),
            config.filter_inactive_over_week,
            config.max_jobs_per_task,
            config.greet_wait_min_seconds,
            config.greet_wait_max_seconds,
        )
        await self.browser.start()
        logger.info("[boss] 浏览器已就绪，准备打开搜索页 task_id=%s", task_id)
        await self._open_search(job_seek_task)
        logger.info(
            "[boss] 搜索页已就绪，开始遍历岗位 task_id=%s max_jobs=%s",
            task_id,
            config.max_jobs_per_task,
        )
        stats = await self._walk_jobs(job_seek_task, config)
        logger.info(
            "[boss] 任务执行统计 task_id=%s visited=%s detail_loaded=%s handled=%s skipped=%s greeted=%s errors=%s",
            task_id,
            stats.visited,
            stats.detail_loaded,
            stats.handled,
            stats.skipped,
            stats.greeted,
            stats.errors,
        )
        if stats.visited > 0 and stats.detail_loaded == 0:
            raise RuntimeError(
                f"遍历了 {stats.visited} 个岗位，但没有成功获取任何岗位详情，请检查页面或接口是否变化。"
            )
        if stats.visited > 0 and stats.handled == 0:
            raise RuntimeError(
                f"获取了 {stats.detail_loaded} 个岗位详情，但没有任何岗位被成功处理，请检查数据库或页面交互。"
            )
        logger.info("[boss] 任务执行结束 task_id=%s", task_id)

    async def _open_search(self, job_seek_task: JobSeekTask) -> None:
        """进入搜索页，校验首屏列表接口并等待岗位列表 DOM 就绪。"""
        search_url = self.build_search_url(job_seek_task)
        logger.info("[boss] 打开搜索页 url=%s", search_url)
        payload = await self.browser.capture_json(
            locators.JOB_LIST_API,
            lambda: self.browser.navigate(search_url),
            timeout=self.LIST_TIMEOUT,
        )
        logger.info("[boss] 首屏列表接口等待结束，开始校验")
        self._validate_list_payload(payload)
        logger.info("[boss] 首屏列表接口校验通过，等待列表 DOM")
        await self.browser.wait_for_element(
            locators.JOB_LIST_CONTAINER,
            timeout=self.LIST_TIMEOUT,
        )
        logger.info("[boss] 岗位列表 DOM 已出现")

    async def _walk_jobs(
        self,
        job_seek_task: JobSeekTask,
        config: GlobalConfig,
    ) -> JobWalkStats:
        """逐个浏览岗位并渐进滚动，返回本轮执行统计。"""
        next_index = 1
        stagnant_scrolls = 0
        stats = JobWalkStats()

        while stagnant_scrolls < self.MAX_STAGNANT_SCROLLS:
            if stats.visited >= config.max_jobs_per_task:
                logger.info(
                    "[boss] 已达到单任务岗位上限 max_jobs=%s，停止继续浏览",
                    config.max_jobs_per_task,
                )
                break

            cards = await self.browser.elements(locators.JOB_CARD, timeout=2)
            logger.info(
                "[boss] 岗位列表状态 loaded=%s next_index=%s stagnant=%s/%s",
                len(cards),
                next_index,
                stagnant_scrolls,
                self.MAX_STAGNANT_SCROLLS,
            )

            if next_index < len(cards):
                # 每次只处理当前岗位。只有当前卡片不在舒适阅读区时才滚动，
                # 滚动距离由卡片在当前视口中的实际位置决定。
                card = cards[next_index]
                logger.info("[boss] 开始处理岗位 #%s", next_index + 1)
                stats.visited += 1
                await self._position_card_for_reading(card)
                await self._process_card(job_seek_task, config, card, next_index, stats)
                logger.info("[boss] 岗位 #%s 处理完成", next_index + 1)
                next_index += 1
                stagnant_scrolls = 0
                continue

            # 当前已经追上所有已加载卡片。只要还没达到全局配置的岗位上限，
            # 就尝试继续加载；连续多次加载不到新岗位时自然结束任务。
            before_count = len(cards)
            logger.info(
                "[boss] 已到当前列表尾部 loaded=%s visited=%s/%s，开始尝试加载更多",
                before_count,
                stats.visited,
                config.max_jobs_per_task,
            )
            payload = await self._load_more()
            self._validate_list_payload(payload, allow_missing=True)

            cards_after_scroll = await self.browser.elements(locators.JOB_CARD, timeout=2)
            if len(cards_after_scroll) > before_count:
                logger.info(
                    "[boss] 加载到新岗位 before=%s after=%s",
                    before_count,
                    len(cards_after_scroll),
                )
                stagnant_scrolls = 0
            else:
                stagnant_scrolls += 1
                logger.info(
                    "[boss] 本轮未发现新岗位 loaded=%s stagnant=%s/%s",
                    len(cards_after_scroll),
                    stagnant_scrolls,
                    self.MAX_STAGNANT_SCROLLS,
                )

        return stats

    async def _process_card(
        self,
        job_seek_task: JobSeekTask,
        config: GlobalConfig,
        card: Any,
        index: int,
        stats: JobWalkStats | None = None,
    ) -> None:
        """处理单个岗位；单岗位失败不会终止整条搜索任务。"""
        stats = stats or JobWalkStats()
        detail: dict[str, Any] | None = None
        try:
            card_text = await self.browser.element_text(card)
            preview = " ".join(card_text.split())[:120]
            logger.info("[boss] 岗位 #%s 卡片内容=%s", index + 1, preview)
            logger.info("[boss] 岗位 #%s 点击并等待详情接口", index + 1)
            detail = await self._load_detail(card)
            if detail is None:
                stats.errors += 1
                logger.warning("[boss] 岗位 #%s 未捕获到详情接口，已跳过", index + 1)
                return

            stats.detail_loaded += 1

            if self.job_records is not None:
                task_id = getattr(job_seek_task, "id", None)
                record = self.job_records.upsert_detail(detail, task_id)
                logger.info(
                    "[boss] 岗位 #%s 已保存历史记录 job_key=%s visits=%s greeted=%s",
                    index + 1,
                    record.job_key,
                    record.visit_count,
                    record.greeted,
                )
                if record.greeted:
                    stats.handled += 1
                    stats.skipped += 1
                    logger.info("[boss] 岗位 #%s 本地历史已打过招呼，跳过", index + 1)
                    return

            not_greeted_reason = self._not_greeted_reason(detail, config)
            if not_greeted_reason is not None:
                if self.job_records is not None:
                    self.job_records.mark_not_greeted(detail, not_greeted_reason)
                stats.handled += 1
                stats.skipped += 1
                logger.info(
                    "[boss] 岗位 #%s 详情判断结果=跳过 reason=%s",
                    index + 1,
                    not_greeted_reason,
                )
                return

            logger.info("[boss] 岗位 #%s 详情判断结果=打招呼", index + 1)
            await self._greet(detail, config)
            stats.handled += 1
            stats.greeted += 1
        except Exception as exc:
            stats.errors += 1
            if detail is not None and self.job_records is not None:
                self.job_records.mark_not_greeted(detail, f"处理异常：{exc}")
            logger.exception("处理岗位 #%s 失败，继续下一个岗位", index + 1)

    async def _load_detail(self, card: Any) -> dict[str, Any] | None:
        """点击岗位卡片并等待 ``job/detail.json``，返回其结构化 JSON。"""
        await self._random_action_delay("点击岗位详情", self.DETAIL_CLICK_DELAY)

        logger.info("[boss] 开始监听岗位详情接口")
        payload = await self.browser.capture_json(
            locators.JOB_DETAIL_API,
            lambda: self.browser.click_element(card),
            timeout=self.DETAIL_TIMEOUT,
        )
        if not self._is_success_payload(payload):
            logger.warning("[boss] 岗位详情接口无有效数据")
            return None
        logger.info("[boss] 岗位详情接口获取成功")
        return payload

    def _not_greeted_reason(
        self,
        detail: dict[str, Any],
        config: GlobalConfig | None = None,
    ) -> str | None:
        """返回不打招呼的具体原因；返回 ``None`` 表示可以打招呼。"""
        config = config or GlobalConfig()
        data = detail.get("zpData")
        if not isinstance(data, dict):
            return "岗位详情数据异常：缺少 zpData"

        job_info = data.get("jobInfo") or {}
        if not isinstance(job_info, dict):
            return "岗位详情数据异常：缺少 jobInfo"

        job_name = str(job_info.get("jobName") or "")
        if job_info.get("invalidStatus") is True:
            return "岗位已失效"

        status = str(job_info.get("jobStatusDesc") or "")
        if "停止" in status:
            return f"岗位状态不允许沟通：{status}"

        keyword = self._match_keyword(job_name, config.job_blacklist)
        if keyword:
            return f"职位命中黑名单：{keyword}"

        brand_info = data.get("brandComInfo") or {}
        brand_name = brand_info.get("brandName", "") if isinstance(brand_info, dict) else ""
        keyword = self._match_keyword(str(brand_name), config.company_blacklist)
        if keyword:
            return f"公司命中黑名单：{keyword}"

        description = str(job_info.get("postDescription") or "")
        keyword = self._match_keyword(description, config.description_blacklist)
        if keyword:
            return f"岗位描述命中黑名单：{keyword}"

        boss_info = data.get("bossInfo") or {}
        active_desc = str(boss_info.get("activeTimeDesc") or "") if isinstance(boss_info, dict) else ""
        if config.filter_inactive_over_week and any(unit in active_desc for unit in ("周", "月", "年")):
            return f"招聘者长期不活跃：{active_desc}"

        relation = data.get("relationInfo") or {}
        if isinstance(relation, dict) and (
            relation.get("interestJob") is True or relation.get("beFriend") is True
        ):
            return "已经与该岗位建立沟通关系"

        logger.info("[boss] 详情判断：岗位可以打招呼 job=%s", job_name)
        return None

    def _should_greet(
        self,
        detail: dict[str, Any],
        config: GlobalConfig | None = None,
    ) -> bool:
        """兼容布尔判断；具体原因由 ``_not_greeted_reason`` 提供。"""
        return self._not_greeted_reason(detail, config) is None

    async def _greet(self, detail: dict[str, Any], config: GlobalConfig) -> None:
        """点击打招呼入口，并关闭随后出现的沟通弹窗。"""
        job_name = detail.get("zpData", {}).get("jobInfo", {}).get("jobName", "")
        await self._random_action_delay("点击打招呼", self.GREET_CLICK_DELAY)
        logger.info("[boss] 点击打招呼按钮 job=%s", job_name)
        await self.browser.click(locators.GREET_BUTTON)
        if self.job_records is not None:
            self.job_records.mark_greeted(detail)
            logger.info("[boss] 已记录岗位打招呼状态 job=%s", job_name)
        logger.info("[boss] 打招呼按钮点击完成，尝试关闭弹窗 job=%s", job_name)

        await self._random_action_delay("关闭打招呼弹窗", self.DIALOG_CLOSE_DELAY)
        closed = await self.browser.click_if_present(
            locators.GREET_STAY_PAGE,
            timeout=self.GREET_DIALOG_TIMEOUT,
        )
        if not closed:
            logger.info("[boss] 未找到可见的留在当前页按钮，尝试右上角关闭按钮 job=%s", job_name)
            closed = await self.browser.click_if_present(
                locators.GREET_DIALOG_CLOSE,
                timeout=self.GREET_DIALOG_TIMEOUT,
            )

        logger.info("[boss] 打招呼后弹窗关闭结果 job=%s closed=%s", job_name, closed)
        await self._random_action_delay(
            "打招呼后等待",
            (config.greet_wait_min_seconds, config.greet_wait_max_seconds),
        )

    @staticmethod
    def _match_keyword(text: str, keywords: list[str]) -> str | None:
        normalized = text.casefold()
        for keyword in keywords:
            candidate = keyword.strip()
            if candidate and candidate.casefold() in normalized:
                return candidate
        return None

    async def _random_action_delay(
        self,
        action: str,
        delay_range: tuple[float, float],
    ) -> None:
        """在页面关键交互前随机等待，并记录实际等待时间。"""
        delay = random.uniform(*delay_range)
        logger.info("[boss] %s 前随机等待 %.2fs", action, delay)
        await asyncio.sleep(delay)

    async def _position_card_for_reading(self, card: Any) -> None:
        """只在当前岗位偏离阅读区时滚动，让逐岗位浏览自然推进页面。"""
        viewport_height = await self.browser.viewport_height()
        logger.info("[boss] 当前视口高度=%s", viewport_height)
        if viewport_height <= 0:
            logger.info("[boss] 无法读取视口高度，直接将岗位滚动到可视区域")
            await self.browser.scroll_element_into_view(card)
            return

        box = await self.browser.element_viewport_box(card)
        top = box["top"]
        bottom = box["bottom"]
        logger.info("[boss] 当前岗位视口位置 top=%.1f bottom=%.1f", top, bottom)

        # 完全在视口外时先让浏览器把元素带进来，避免一次滚动距离过大。
        if bottom <= 0 or top >= viewport_height:
            logger.info("[boss] 当前岗位完全在视口外，滚动到可视区域")
            await self.browser.scroll_element_into_view(card)
            return

        comfortable_bottom = viewport_height * self.CARD_READ_BOTTOM_RATIO

        # 按岗位顺序浏览时保持页面整体向下推进。岗位已经处于视口上方区域时不再反向滚动，
        # 避免出现“看一个岗位就上下抖一下”的不自然效果。
        if bottom <= comfortable_bottom:
            logger.info("[boss] 当前岗位已在可读区域，无需滚动")
            return

        # 岗位偏下时只滚动实际超出的距离，并限制单次最大滚动量。
        # 不设置最小滚动量，避免只超出十几像素却强制滚动 80px 导致过冲。
        distance = int(bottom - comfortable_bottom)
        delta = -min(self.CARD_SCROLL_MAX, distance)
        logger.info("[boss] 当前岗位偏下，向上滑动 delta=%s", delta)
        await self.browser.scroll(delta)

    async def _load_more(self) -> dict[str, Any] | None:
        """用多次短距离随机下滑触发懒加载，并监听下一批岗位接口。"""

        async def progressive_scroll() -> None:
            min_times, max_times = self.LOAD_MORE_SCROLL_TIMES
            min_delta, max_delta = self.LOAD_MORE_SCROLL_DELTA
            min_pause, max_pause = self.LOAD_MORE_SCROLL_PAUSE

            times = random.randint(min_times, max_times)
            logger.info("[boss] 加载更多：计划进行 %s 次小幅滚动", times)
            for index in range(times):
                delta = random.randint(min_delta, max_delta)
                pause = random.uniform(min_pause, max_pause)
                logger.info(
                    "[boss] 加载更多：第 %s/%s 次滚动 delta=%s pause=%.2fs",
                    index + 1,
                    times,
                    delta,
                    pause,
                )
                await self.browser.scroll_page(delta)
                await asyncio.sleep(pause)

        return await self.browser.capture_json(
            locators.JOB_LIST_API,
            progressive_scroll,
            timeout=self.LOAD_MORE_TIMEOUT,
        )

    @staticmethod
    def _is_success_payload(payload: dict[str, Any] | None) -> bool:
        return isinstance(payload, dict) and payload.get("code") == 0

    def _validate_list_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        allow_missing: bool = False,
    ) -> None:
        if payload is None and allow_missing:
            logger.info("[boss] 本次未捕获岗位列表接口，允许继续观察 DOM")
            return
        if not self._is_success_payload(payload):
            logger.error("[boss] 岗位列表接口加载失败或响应无效")
            raise RuntimeError("BOSS 岗位列表接口加载失败或未捕获到有效响应。")
        logger.info("[boss] 岗位列表接口响应有效")
