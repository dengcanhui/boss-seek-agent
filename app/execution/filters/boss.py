from __future__ import annotations

import logging
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
                "判断候选人现有技术背景与岗位实际主要工作内容是否有重大差距。"
                "匹配不等于精通每项技术，部分技能缺失、对框架不熟悉、经验略有不足可以接受。"
                "必须以详细岗位职责为主，岗位标题和技术关键词不能替代实际工作内容。"
                "先判断岗位主要任务是否涉及软件研发、代码实现或技术系统建设。"
                "如果职责明确以电话销售、客户开发、商务招商、非技术运营、硬件研发等为主，"
                "即使岗位标题含Python/Agent/AI开发、出现技术名词，也必须选 major_gap。"
                "例如岗位标题为Python Agent开发，正文却写主要工作是电话销售AI产品、无需写代码，"
                "必须判为 major_gap，而不是 acceptable。"
                "主要研发技术栈完全不同且难以胜任，也选择 major_gap。"
                "岗位属于相关开发方向但技术细节不全时默认 acceptable。"
            ),
            "criteria": {
                "acceptable": "主要工作与候选人的现有技术或目标研发方向大体相关，允许部分技能差距与信息缺失",
                "major_gap": "主要职责不是相关软件研发工作，或主要技术跨度过大难以胜任；标题技术词不构成匹配",
            },
        },
        "hard_conflict": {
            "type": "choice",
            "instructions": (
                "只判断岗位明确的必须条件是否与候选人画像的已知事实、明确不能接受的事项直接冲突。"
                "例如：岗位要求硕士而候选人是本科；要求5年以上总经验但候选人只有3年；"
                "明确写单休而用户不接受单休；明确要求线下面试而用户拒绝现场面试。"
                "只在招聘文本存在明确相反证据时选择 conflict。"
                "未提及休息制度、面试方式、加班或出差等，一律选 no_proven_conflict，默认放行；"
                "即使用户说必须双休，JD 未提及也不能算冲突。"
                "优先条件不是必须条件；画像未提供年龄、专业、证书或某项技能，"
                "绝不能当成已知不符合。例如岗位写30岁以下但画像没有年龄，不存在明确冲突。"
                "3年经验与岗位写3年以上不构成已证实的直接矛盾；5年以上与已知3年则明确冲突。"
                "不要根据岗位名称或公司行业等猜测隐含条件。"
            ),
            "criteria": {
                "conflict": "岗位明确的必须条件与候选人的已知事实或不可接受事项有直接矛盾",
                "no_proven_conflict": "没有明确冲突证据，包括未提及相关条件或尚未证实的条件",
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
        active_desc = str(boss.get("activeTimeDesc") or "")
        if config.filter_inactive_over_week and any(
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
        """先执行明确规则；启用 AI 时仅做一次双维度岗位判断。"""
        result = self.check_detail_rules(detail, config)
        if not result.passed:
            return result
        if not config.ai_greeting_filter_enabled:
            return FilterResult.allow()
        return await self.check_model(detail, search_keyword=search_keyword)

    @classmethod
    def compact_model_state(cls, state: dict[str, Any]) -> dict[str, Any]:
        """仅保留技术背景、学历年限和明确拒绝的岗位条件，并裁剪超长 JD。"""
        candidate = state.get("candidate") or {}
        job = state.get("job") or {}
        description = str(job.get("description") or "")
        if len(description) > cls.MAX_DESCRIPTION_CHARS:
            description = (
                description[:1000].rstrip()
                + "\n...（中间内容已省略）...\n"
                + description[-800:].lstrip()
            )
        preferences = candidate.get("job_preferences") or {}
        return {
            "candidate": {
                **{
                    key: candidate[key]
                    for key in ("expected_jobs", "skills", "experience_years", "degree")
                    if key in candidate
                },
                "job_preferences": {"required": preferences.get("required") or []},
            },
            "search_keyword": state.get("search_keyword") or "",
            "job": {
                "title": job.get("title"),
                "description": description,
            },
        }

    async def check_model(
        self,
        detail: dict[str, Any],
        *,
        search_keyword: str = "",
        profile: CandidateProfile | None = None,
    ) -> FilterResult:
        """使用 tev1 模型判断匹配；连接或结果错误时拒绝打招呼。"""
        data = detail.get("zpData")
        data = data if isinstance(data, dict) else {}
        job = data.get("jobInfo")
        job = job if isinstance(job, dict) else {}
        try:
            if self.profile_service is None or self.model_client is None:
                return FilterResult.reject("AI 过滤：模型或候选人画像未配置")
            profile = profile or self.profile_service.get_profile()
            if not profile.expected_jobs and not profile.skills and not search_keyword:
                return FilterResult.reject("AI 过滤：未提供求职方向或核心技能，无法判断匹配度")

            state = {
                "candidate": profile.model_dump(
                    include={"expected_jobs", "skills", "experience_years", "degree", "job_preferences"},
                ),
                "search_keyword": search_keyword,
                "job": {
                    "title": job.get("jobName"),
                    "description": str(job.get("postDescription") or ""),
                },
            }
            result = await self.model_client.evaluate(
                state=self.compact_model_state(state),
                questions=self.QUESTIONS,
            )
            decision = self.parse_decision(result)
            logger.info(
                "[boss] Ollama 决策 job=%s greet=%s reason=%s",
                job.get("jobName"),
                decision.passed,
                decision.reason,
            )
            return decision
        except Exception:
            logger.exception("[boss] Ollama System One 决策失败 job=%s", job.get("jobName"))
            return FilterResult.reject("AI 过滤：Ollama 调用失败或返回无效结果")

    @classmethod
    def parse_decision(cls, payload: dict[str, Any]) -> FilterResult:
        """只判断技术差距是否过大、是否存在明确的硬性冲突。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise ValueError("System One 响应缺少 answers")
        answers = payload["answers"]
        expected_labels = {
            "core_skill": {"acceptable", "major_gap"},
            "hard_conflict": {"conflict", "no_proven_conflict"},
        }
        choices: dict[str, str] = {}
        probabilities: dict[str, dict[str, float]] = {}

        for name, allowed in expected_labels.items():
            answer = answers.get(name)
            if not isinstance(answer, dict):
                raise ValueError(f"缺少决策字段 {name}")
            choice = answer.get("choice")
            probs = answer.get("probabilities")
            if choice not in allowed or not isinstance(probs, dict) or not allowed <= probs.keys():
                raise ValueError(f"决策字段 {name} 不合法")
            if any(type(probs[key]) not in {int, float} or not 0 <= probs[key] <= 1 for key in allowed):
                raise ValueError(f"决策字段 {name} 概率不合法")
            choices[name] = choice
            probabilities[name] = {key: float(probs[key]) for key in allowed}

        conflict_prob = probabilities["hard_conflict"]["conflict"]
        confirmed_conflict = (
            choices["hard_conflict"] == "conflict"
            and conflict_prob >= cls.MIN_CONFIRMED_CONFLICT_PROB
        )
        approved = choices["core_skill"] != "major_gap" and not confirmed_conflict
        skill = "技术差距可接受" if choices["core_skill"] == "acceptable" else "核心技术差距过大"
        if confirmed_conflict:
            hard = "存在明确硬性条件冲突"
        elif choices["hard_conflict"] == "conflict":
            hard = "疑似冲突但证据不足，暂不否决"
        else:
            hard = "无明确硬性冲突"
        reason = (
            f"核心技术：{skill}；硬性条件：{hard}"
            f"（冲突概率 {probabilities['hard_conflict']['conflict']:.2f}）"
        )
        return FilterResult(approved, "AI 过滤：" + ("通过；" if approved else "未通过；") + reason)
