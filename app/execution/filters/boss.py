from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from app.application.candidate.candidate_profile_service import CandidateProfileService
from app.domain.candidate.models import CandidateProfile
from app.domain.global_config import GlobalConfig

from .base import BaseJobFilter, FilterResult

logger = logging.getLogger("uvicorn.error.boss")


class DecisionModelClient(Protocol):
    """决策模型调用接口；具体 HTTP 实现位于 infrastructure。"""

    async def evaluate(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]: ...


class BossJobFilter(BaseJobFilter):
    """统一管理 BOSS 岗位的卡片预过滤、详情规则和模型判断。"""

    # 保留 JD 开头与结尾的职责、任职要求，避免超过 System One token 限制。
    MAX_DESCRIPTION_CHARS = 1800
    # 模型对硬性冲突不够确定时，避免仅凭猜测错过岗位。
    MIN_CONFIRMED_CONFLICT_PROB = 0.80

    QUESTIONS: dict[str, dict[str, Any]] = {
        "core_skill": {
            "type": "choice",
            "instructions": (
                "判断候选人的现有技能是否能够胜任岗位的核心工作。"
                "仅依据候选人skills和岗位JD判断，不考虑学历、工作年限及个人偏好。"
                "首先识别岗位的主要工作职责及必备核心技能，"
                "区分核心技能与辅助技能、优先技能。"
                "然后比较候选人的skills与岗位核心技能，"
                "同时考虑技能之间的关联性、可迁移性和专业领域差异。"
                "如果候选人具备完成主要工作的基础能力，"
                "即使缺少部分框架、工具或非核心技能，也选择acceptable。"
                "如果岗位主要工作依赖候选人明显缺乏的专业知识或核心技能，"
                "且现有技能难以迁移，则选择major_gap。"
                "不得仅因双方出现相同技术关键词就认定匹配，"
                "也不得仅因技术名称不同就认定不匹配。"
                "以岗位实际职责为主要依据，岗位标题仅作为参考。"
                "不得假设候选人具备skills中未体现的专业能力。"
                "岗位信息不完整时，不得凭空推断存在重大技能差距。"
            ),
            "criteria": {
                "acceptable": "具备胜任岗位核心工作的基础能力，允许部分技能缺失或合理迁移",
                "major_gap": "缺乏岗位所必需的核心专业能力，且技能难以直接迁移",
            },
        },
        "hard_conflict": {
            "type": "choice",
            "instructions": (
                "只比较候选人 required 列表中的个人底线与岗位 JD 的明确事实。"
                "required 是唯一判断依据，不能增加任何未列在 required 中的要求。"
                "学历、工作年限、技术栈、架构经验、职业方向等招聘门槛一律不参与本问题，"
                "即使 JD 明确要求5年以上经验、硕士或某个框架，也绝对不能因此选 conflict。"
                "例如 required 是只接受双休，JD 明确写单休或大小休，才选 conflict；"
                "required 是只接受线上面试，JD 明确要求现场/线下面试，才选 conflict。"
                "岗位没有写休息安排、面试方式等底线相关信息时，"
                "必须选择 no_proven_conflict，不能把未知当成冲突。"
                "JD 中的'线上服务'、'人工介入'、'上线运营'不代表面试方式；"
                "不可以根据岗位名称、行业或招聘难度猜测工作制度。"
                "优先条件或对某种安排的否定描述也不等于违反底线。"
                "只在岗位原文出现与 required 直接相反的证据时选择 conflict。"
            ),
            "criteria": {
                "conflict": "岗位 JD 明确违反 required 中至少一项个人底线，并有直接文本证据",
                "no_proven_conflict": "JD 未明确违反 required；包括未提及、无法确认或无关招聘要求",
            },
        },
    }

    def __init__(
        self,
        profile_service: CandidateProfileService | None = None,
        model_client: DecisionModelClient | None = None,
    ) -> None:
        self.profile_service: CandidateProfileService | None = profile_service
        self.model_client: DecisionModelClient | None = model_client

    @staticmethod
    def _match_keyword(text: str, keywords: list[str]) -> str | None:
        normalized = text.casefold()
        for keyword in keywords:
            word = keyword.strip()
            if word and word.casefold() in normalized:
                return word
        return None

    def check_card(self, card_text: str, config: GlobalConfig) -> FilterResult:
        """卡片包含岗位名和公司名；命中任一黑名单则不打开详情。

        卡片是组合文本，无法区分同一个词出现在岗位名还是公司名。
        详情阶段仍以各独立字段进行精确验证。
        """
        keyword = self._match_keyword(card_text, config.job_blacklist)
        if keyword:
            return FilterResult.reject(f"卡片文本命中职位黑名单：{keyword}")
        keyword = self._match_keyword(card_text, config.company_blacklist)
        if keyword:
            return FilterResult.reject(f"卡片文本命中公司黑名单：{keyword}")
        return FilterResult.allow()

    def check_detail_rules(self, detail: dict[str, Any], config: GlobalConfig) -> FilterResult:
        """详情字段验证及用户配置规则，优先于模型判断。"""
        data = detail.get("zpData")
        if not isinstance(data, dict):
            return FilterResult.reject("岗位详情数据异常：缺少 zpData")

        job = data.get("jobInfo")
        if not isinstance(job, dict):
            return FilterResult.reject("岗位详情数据异常：缺少 jobInfo")

        if job.get("invalidStatus") is True:
            return FilterResult.reject("岗位已失效")

        status = str(job.get("jobStatusDesc") or "")
        if "停止" in status:
            return FilterResult.reject(f"岗位状态不允许沟通：{status}")

        keyword = self._match_keyword(str(job.get("jobName") or ""), config.job_blacklist)
        if keyword:
            return FilterResult.reject(f"职位命中黑名单：{keyword}")

        company = data.get("brandComInfo")
        company = company if isinstance(company, dict) else {}
        keyword = self._match_keyword(str(company.get("brandName") or ""), config.company_blacklist)
        if keyword:
            return FilterResult.reject(f"公司命中黑名单：{keyword}")

        keyword = self._match_keyword(
            str(job.get("postDescription") or ""), config.description_blacklist,
        )
        if keyword:
            return FilterResult.reject(f"岗位描述命中黑名单：{keyword}")

        boss = data.get("bossInfo")
        boss = boss if isinstance(boss, dict) else {}
        active_desc = str(boss.get("activeTimeDesc") or "").strip()
        if config.filter_inactive_over_week and "本周" not in active_desc and any(
            unit in active_desc for unit in ("周", "月", "年")
        ):
            return FilterResult.reject(f"招聘者长期不活跃：{active_desc}")

        relation = data.get("relationInfo")
        if isinstance(relation, dict) and (
            relation.get("interestJob") is True or relation.get("beFriend") is True
        ):
            return FilterResult.reject("已经与该岗位建立沟通关系")

        return FilterResult.allow()

    async def check_detail(
        self,
        detail: dict[str, Any],
        config: GlobalConfig,
        *,
        search_keyword: str = "",
    ) -> FilterResult:
        """先执行确定性规则；AI 分两次、按需进行技能与个人底线判断。"""
        result = self.check_detail_rules(detail, config)
        if not result.passed:
            return result
        if not config.ai_greeting_filter_enabled:
            return FilterResult.allow()
        return await self.check_model(detail, search_keyword=search_keyword)

    @staticmethod
    def _explicit_required_conflict(description: str, required: list[str]) -> str | None:
        """兜底识别 JD 中明确违反个人底线的安排，避免小模型漏判。"""
        if any("双休" in item or any(
            term in item for term in ("不接受单休", "不接受大小周", "不接受大小休")
        ) for item in required):
            for sentence in re.split(r"[。；;\n]", description):
                if re.search(r"大小休|大小周|单休|做六休一", sentence):
                    if not re.search(r"不实行|不采用|不接受|没有|取消|拒绝|禁止|无大小|非大小", sentence):
                        return "JD 明确写有单休或大小周/大小休"

        if any("线上面试" in item or any(
            term in item for term in ("不接受线下面试", "不接受现场面试")
        ) for item in required):
            for sentence in re.split(r"[。；;\n]", description):
                if re.search(r"(?:必须|要求|需要|只能|统一|一律)(?:到场|现场|线下)面试|"
                             r"面试(?:必须|要求|方式|形式)[：:]?(?:到场|现场|线下)", sentence):
                    if not re.search(r"线上或线下|线下或线上|均可|可线上|也可线上", sentence):
                        return "JD 明确要求线下面试"
        return None

    @staticmethod
    def _answer(payload: dict[str, Any], name: str) -> tuple[str, float]:
        """解析单问题的 System One 响应，返回选择及拒绝概率。"""
        labels = {
            "core_skill": ("acceptable", "major_gap"),
            "hard_conflict": ("no_proven_conflict", "conflict"),
        }[name]
        answers = payload.get("answers") if isinstance(payload, dict) else None
        answer = answers.get(name) if isinstance(answers, dict) else None
        if not isinstance(answer, dict):
            raise ValueError(f"System One 响应缺少 {name}")
        choice, probs = answer.get("choice"), answer.get("probabilities")
        if choice not in labels or not isinstance(probs, dict):
            raise ValueError(f"System One {name} 结果不合法")
        if any(type(probs.get(key)) not in (int, float) or not 0 <= probs[key] <= 1 for key in labels):
            raise ValueError(f"System One {name} 概率不合法")
        return choice, float(probs[labels[1]])

    async def check_model(
        self,
        detail: dict[str, Any],
        *,
        search_keyword: str = "",
        profile: CandidateProfile | None = None,
    ) -> FilterResult:
        """先判断技能，再判断个人底线；两次请求的候选人信息完全隔离。"""
        try:
            if self.model_client is None or (profile is None and self.profile_service is None):
                return FilterResult.reject("AI 过滤：模型或候选人画像未配置")
            if profile is None:
                profile = self.profile_service.get_profile()
            if not profile.skills:
                return FilterResult.reject("AI 过滤：未提供核心技能")

            job = detail.get("zpData", {}).get("jobInfo", {})
            description = str(job.get("postDescription") or "")
            compact = description
            if len(compact) > self.MAX_DESCRIPTION_CHARS:
                compact = compact[:1000].rstrip() + "\n...（中间内容已省略）...\n" + compact[-800:].lstrip()

            skill = await self.model_client.evaluate(
                state={
                    "candidate": {"skills": profile.skills},
                    "job": {"title": job.get("jobName"), "description": compact},
                },
                questions={"core_skill": self.QUESTIONS["core_skill"]},
            )
            skill_choice, _ = self._answer(skill, "core_skill")
            if skill_choice == "major_gap":
                return FilterResult.reject("AI 过滤：未通过；核心技术差距过大")

            required = profile.job_preferences.required
            if not required:
                return FilterResult(True, "AI 过滤：通过；核心技术匹配；未设置个人底线")

            hard = await self.model_client.evaluate(
                state={"candidate": {"required": required}, "job": {"description": compact}},
                questions={"hard_conflict": self.QUESTIONS["hard_conflict"]},
            )
            hard_choice, conflict_prob = self._answer(hard, "hard_conflict")
            evidence = self._explicit_required_conflict(description, required)
            blocked = bool(evidence) or (
                hard_choice == "conflict" and conflict_prob >= self.MIN_CONFIRMED_CONFLICT_PROB
            )
            reason = evidence or ("疑似个人底线冲突" if blocked else "无明确个人底线冲突")
            result = FilterResult(
                not blocked,
                f"AI 过滤：{'未通过' if blocked else '通过'}；核心技术匹配；"
                f"硬性条件：{reason}（冲突概率 {conflict_prob:.2f}）",
            )
            logger.info("[boss] Ollama 决策 job=%s result=%s", job.get("jobName"), result.reason)
            return result
        except Exception:
            logger.exception("[boss] Ollama System One 决策失败")
            return FilterResult.reject("AI 过滤：Ollama 调用失败或返回无效结果")
