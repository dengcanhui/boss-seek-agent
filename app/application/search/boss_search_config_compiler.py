from __future__ import annotations

from app.domain.search.models import BossSearchConfig, JobSeekTaskParams

from .boss_search_options import BossOptions, load_boss_options


MULTI_FIELDS = ("experience", "degree", "industry", "scale", "stage")


class BossSearchConfigCompiler:
    """把人类语义搜索条件编译为与 BOSS 搜索 URL 一致的参数快照。"""

    def __init__(self, options: BossOptions | None = None):
        self.options: BossOptions = options if options is not None else load_boss_options()

    def _one(self, field: str, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        if not normalized:
            return None
        mapping = self.options.get(field, {})
        if normalized in mapping:
            code = mapping[normalized]
            return None if code == "0" else code
        raise ValueError(f"未知 {field}: {normalized}")

    def _many(self, field: str, values: list[str] | None) -> list[str]:
        if not values:
            return []
        mapping = self.options.get(field, {})
        if not mapping:
            raise ValueError(f"{field} 暂未配置可用选项")
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized not in mapping:
                raise ValueError(f"未知 {field}: {normalized}")
            code = mapping[normalized]
            if code != "0" and code not in result:
                result.append(code)
        return result

    @staticmethod
    def _required(field: str, value: str | None) -> str:
        normalized = value.strip() if value else ""
        if not normalized:
            raise ValueError(f"{field} 不能为空")
        return normalized

    def compile(self, params: JobSeekTaskParams) -> BossSearchConfig:
        query = self._required("query", params.query)
        city_name = self._required("city", params.city)
        city = self._one("city", city_name)
        if city is None:
            raise ValueError("city 不能为空")

        return BossSearchConfig(
            query=query,
            city=city,
            jobType=self._one("jobType", params.jobType),
            salary=self._one("salary", params.salary),
            experience=self._many("experience", params.experience),
            degree=self._many("degree", params.degree),
            industry=self._many("industry", params.industry),
            scale=self._many("scale", params.scale),
            stage=self._many("stage", params.stage),
        )

    def compile_update(
        self,
        current: BossSearchConfig,
        changes: JobSeekTaskParams,
    ) -> BossSearchConfig:
        data = current.model_dump()
        fields = changes.model_fields_set

        if "query" in fields:
            data["query"] = self._required("query", changes.query)
        if "city" in fields:
            city_name = self._required("city", changes.city)
            city = self._one("city", city_name)
            if city is None:
                raise ValueError("city 不能为空")
            data["city"] = city
        if "jobType" in fields:
            data["jobType"] = self._one("jobType", changes.jobType)
        if "salary" in fields:
            data["salary"] = self._one("salary", changes.salary)
        for field in MULTI_FIELDS:
            if field in fields:
                data[field] = self._many(field, getattr(changes, field))

        return BossSearchConfig.model_validate(data)
