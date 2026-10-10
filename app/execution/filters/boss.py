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

    # 初始采用偏保守的阈值，避免低概率的第一名直接触发打招呼。
    # System One 输入有 token 上限，截取首尾以尽量保留职责与任职要求。
    MAX_DESCRIPTION_CHARS = 1800
    MIN_SKILL_MATCH_PROB = 0.55
    MIN_CAREER_ALIGNED_PROB = 0.65
    # 只在存在高置信度、可证实的硬门槛冲突时拒绝。
    MIN_HARD_CONFLICT_PROB = 0.70

    QUESTIONS: dict[str, dict[str, Any]] = {
        "core_skill": {
            "type": "choice",
            "instructions": "候选人现有核心技术栈与该岗位实际主要工作内容有多大匹配度？按实际技术要求判断，不要仅凭职位名称。",
            "criteria": {
                "match": "候选人具备岗位主要核心技能，现有经验能够直接用于该工作",
                "gap": "岗位主要技能与候选人技术栈有明显差距，需要较大跨度转型",
                "unknown": "岗位或候选人提供的技术信息不足，无法判断",
            },
        },
        "hard_conflict": {
            "type": "choice",
            "instructions": (
                "只判断岗位明示的【硬性要求】与候选人画像中【明确已知事实】是否存在直接矛盾。"
                "例如岗位要求硕士而只有本科，岗位要求5年以上总工作经验而候选人只有3年。"
                "年龄或专业未提供、未写某技能或专项项目经历、没有写证书，均不能视为已证实不具备。"
                "写着优先的要求不算硬性门槛。"
                "需要存在确切矛盾才选择 conflict，否则选择 no_proven_conflict，不等于确认完全符合。"
            ),
            "criteria": {
                "conflict": "岗位的必须条件与画像已知事实存在直接冲突，有证据证明不满足",
                "no_proven_conflict": "未发现有证据的直接冲突；可能完全满足，也可能还有未确认条件",
            },
        },
        "career_direction": {
            "type": "choice",
            "instructions": "岗位实际工作职责是否符合候选人的长期目标岗位方向？",
            "criteria": {
                "aligned": "工作内容属于候选人期望的长期职业方向",
                "misaligned": "工作内容与目标方向明显不一致",
                "unknown": "无法从岗位描述判断职业方向",
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
        """严格按 详情规则 -> Ollama 的顺序过滤。"""
        result = self.check_detail_rules(detail, config)
        if not result.passed:
            return result
        # 用户明确说“必须双休”等要求时，先确保岗位能证实满足。
        profile = self.profile_service.get_profile() if self.profile_service else None
        required = profile.job_preferences.required if profile else []
        if required:
            if not config.ai_greeting_filter_enabled or self.model_client is None:
                return FilterResult.reject(
                    "岗位硬性偏好尚未核实：AI 过滤已关闭或模型未配置，不能自动打招呼"
                )
            preference_result = await self.check_job_preferences(detail, required)
            if not preference_result.passed:
                return preference_result

        if not config.ai_greeting_filter_enabled:
            return FilterResult.allow()
        return await self.check_model(detail, search_keyword=search_keyword, profile=profile)

    async def check_job_preferences(
        self,
        detail: dict[str, Any],
        requirements: list[str],
    ) -> FilterResult:
        """核实用户的每条硬性岗位要求。unknown 按未核实处理，不自动打招呼。

        软性偏好不参与否决，避免“最好少加班”变成绝对限制。
        """
        if self.model_client is None:
            return FilterResult.reject("岗位硬性偏好尚未核实：Ollama 未配置")
        data = detail.get("zpData") or {}
        job = data.get("jobInfo") or {}
        for requirement in requirements:
            question = {
                "type": "choice",
                "instructions": (
                    "仅依据招聘岗位的文本，判断该岗位是否明确满足给定的用户硬性要求。"
                    "禁止根据行业、公司名字、岗位名称猜测福利、工时或出差情况。"
                    "要关注否定词，例如“不接受出差”对应的岗位要能确认无需出差。"
                    "没有提及、不够具体或内容互相矛盾时选 unknown，绝不能默认为满足。"
                    "这里的要求是：" + requirement
                ),
                "criteria": {
                    "met": "岗位明确说明满足该要求，有对应事实",
                    "unmet": "岗位明确说明与该要求冲突，如要求双休却写单休或大小周",
                    "unknown": "岗位没有明确说明或无法从描述确认是否满足要求",
                },
            }
            try:
                response = await self.model_client.evaluate(
                    state={
                        "requirement": requirement,
                        "job": self.compact_model_state({
                            "job": {
                                "title": job.get("jobName"),
                                "description": str(job.get("postDescription") or ""),
                            }
                        })["job"],
                    },
                    questions={"preference": question},
                )
                answer = (response.get("answers") or {}).get("preference")
                if not isinstance(answer, dict):
                    raise ValueError("缺少 preference 回答")
                choice = answer.get("choice")
                probabilities = answer.get("probabilities")
                if (
                    choice not in {"met", "unmet", "unknown"}
                    or not isinstance(probabilities, dict)
                    or any(
                        type(probabilities.get(key)) not in (int, float)
                        or not 0 <= probabilities[key] <= 1
                        for key in ("met", "unmet", "unknown")
                    )
                ):
                    raise ValueError("preference 决策或概率不合法")
                if choice != "met" or probabilities["met"] < 0.55:
                    reason = {
                        "unmet": "岗位明确不符合",
                        "unknown": "岗位描述未能确认满足",
                        "met": "满足证据置信度不足",
                    }[choice]
                    return FilterResult.reject(f"岗位硬性偏好未通过：{requirement}（{reason}）")
            except Exception:
                logger.exception("[boss] 岗位硬性偏好判断失败 requirement=%s", requirement)
                return FilterResult.reject(f"岗位硬性偏好未核实：{requirement}（Ollama 调用失败）")
        return FilterResult.allow()

    @classmethod
    def compact_model_state(cls, state: dict[str, Any]) -> dict[str, Any]:
        """删除与三维匹配无关的画像字段并控制岗位描述长度。

        这是模型输入的裁剪，不影响存储的岗位原始详情。
        """
        candidate = state.get("candidate") or {}
        job = state.get("job") or {}
        description = str(job.get("description") or "")
        if len(description) > cls.MAX_DESCRIPTION_CHARS:
            description = (
                description[:1000].rstrip()
                + "\n...（中间内容已省略）...\n"
                + description[-800:].lstrip()
            )
        return {
            "candidate": {
                key: candidate[key]
                for key in ("expected_jobs", "skills", "experience_years", "degree")
                if key in candidate
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
        brand = data.get("brandComInfo")
        brand = brand if isinstance(brand, dict) else {}

        try:
            if self.profile_service is None or self.model_client is None:
                return FilterResult.reject("AI 过滤：模型或候选人画像未配置")
            profile = profile or self.profile_service.get_profile()
            if not profile.expected_jobs and not profile.skills and not search_keyword:
                return FilterResult.reject("AI 过滤：未提供求职方向或核心技能，无法判断匹配度")

            candidate = profile.model_dump(
                include={
                    "expected_jobs",
                    "expected_cities",
                    "skills",
                    "experience_years",
                    "degree",
                    "expected_salary",
                    "company_preferences",
                    "search_preferences",
                },
            )
            state = {
                "candidate": candidate,
                "search_keyword": search_keyword,
                "job": {
                    "title": job.get("jobName"),
                    "company": brand.get("brandName"),
                    "salary": job.get("salaryDesc") or job.get("salary"),
                    "city": job.get("locationName") or job.get("jobArea"),
                    "description": str(job.get("postDescription") or "")[:6000],
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
        """从 System One 的 answers 中读取选择及每个选项的概率。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise ValueError("System One 响应缺少 answers")
        answers = payload["answers"]
        expected_labels = {
            "core_skill": {"match", "gap", "unknown"},
            "hard_conflict": {"conflict", "no_proven_conflict"},
            "career_direction": {"aligned", "misaligned", "unknown"},
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

        match_prob = probabilities["core_skill"]["match"]
        aligned_prob = probabilities["career_direction"]["aligned"]
        conflict_prob = probabilities["hard_conflict"]["conflict"]
        approved = (
            choices["core_skill"] == "match"
            and match_prob >= cls.MIN_SKILL_MATCH_PROB
            and choices["career_direction"] == "aligned"
            and aligned_prob >= cls.MIN_CAREER_ALIGNED_PROB
            and not (
                choices["hard_conflict"] == "conflict"
                and conflict_prob >= cls.MIN_HARD_CONFLICT_PROB
            )
        )
        skill_label = {"match": "匹配", "gap": "不匹配", "unknown": "无法判断"}[
            choices["core_skill"]
        ]
        hard_label = {
            "conflict": "疑似存在冲突",
            "no_proven_conflict": "无已证实冲突",
        }[choices["hard_conflict"]]
        career_label = {"aligned": "一致", "misaligned": "不一致", "unknown": "无法判断"}[
            choices["career_direction"]
        ]
        reason = (
            f"核心技能：{skill_label}(匹配概率 {match_prob:.2f})，"
            f"硬性要求：{hard_label}(冲突概率 {conflict_prob:.2f})，"
            f"职业方向：{career_label}(一致概率 {aligned_prob:.2f})"
        )
        return FilterResult(approved, "AI 过滤：" + ("通过；" if approved else "未通过；") + reason)
