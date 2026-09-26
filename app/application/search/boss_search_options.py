from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from app.agent.tools.decorator import agent_tool


BossOptions = dict[str, dict[str, str]]
SearchOptionField = Literal["city", "industry"]
OPTIONS_FILE = Path(__file__).resolve().parents[3] / "data" / "search_options.json"
OPTION_FIELDS = ("city", "jobType", "salary", "experience", "degree", "industry", "scale", "stage")
SMALL_OPTION_FIELDS = ("jobType", "salary", "experience", "degree", "scale", "stage")


def load_search_options_data(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    """读取并校验 BOSS 搜索选项原始数据。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"BOSS 搜索选项文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"BOSS 搜索选项文件不是有效 JSON: {path}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"BOSS 搜索选项文件顶层必须是对象: {path}")
    return data


def build_boss_options(data: dict[str, Any]) -> BossOptions:
    """把原始选项数据转换成业务层统一使用的名称 -> code 映射。"""
    options: BossOptions = {}
    for field in OPTION_FIELDS:
        items = data.get(field)
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"BOSS 搜索选项缺少有效字段: {field}")

        mapping: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError(f"BOSS 搜索选项 {field} 包含非法条目")
            name = item.get("name")
            code = item.get("code")
            if not isinstance(name, str) or not name.strip():
                raise RuntimeError(f"BOSS 搜索选项 {field} 存在空 name")
            if code in (None, ""):
                raise RuntimeError(f"BOSS 搜索选项 {field} 存在空 code: {name}")

            normalized_name = name.strip()
            normalized_code = str(code)
            existing = mapping.get(normalized_name)
            if existing is not None and existing != normalized_code:
                raise RuntimeError(
                    f"BOSS 搜索选项名称重复且 code 不一致: {field}.{normalized_name}"
                )
            mapping[normalized_name] = normalized_code

        options[field] = mapping
    return options


def load_boss_options(path: Path = OPTIONS_FILE) -> BossOptions:
    return build_boss_options(load_search_options_data(path))


class BossSearchOptionsService:
    """向 Compiler、前端和 Agent 提供同一份 BOSS 搜索语义选项。"""

    def __init__(self, path: Path = OPTIONS_FILE):
        self.data: dict[str, Any] = load_search_options_data(path)
        self.options: BossOptions = build_boss_options(self.data)
        self._search_rows: dict[SearchOptionField, list[dict[str, Any]]] = {
            "city": self._rows("city"),
            "industry": self._rows("industry"),
        }

    def _rows(self, key: str) -> list[dict[str, Any]]:
        rows = self.data.get(key)
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def semantic_guide(self) -> dict[str, Any]:
        """返回适合放进模型上下文的小型语义说明，不包含完整城市/行业列表。"""
        allowed_values = {
            field: [
                name
                for name, code in self.options[field].items()
                if code != "0"
            ]
            for field in SMALL_OPTION_FIELDS
        }
        return {
            "field_rules": {
                "query": "自由搜索关键词，例如 Agent开发、Python后端、大模型应用；不是 BOSS code。",
                "city": "必须使用一个具体的 BOSS 城市名称；不能传省份、区域或 code。不确定名称时调用 search_boss_options(field='city', ...)。",
                "jobType": "单选；只能使用 allowed_values.jobType 中的名称；用户未限制时传 null。",
                "salary": "单选；只能使用 allowed_values.salary 中的薪资档位名称；不能自行创造薪资区间；用户未限制时传 null。",
                "experience": "可多选；只能使用 allowed_values.experience 中的名称；无要求时传 [] 或 null。",
                "degree": "可多选；只能使用 allowed_values.degree 中的名称；无要求时传 [] 或 null。",
                "scale": "可多选；只能使用 allowed_values.scale 中的名称；无要求时传 [] 或 null。",
                "stage": "可多选；只能使用 allowed_values.stage 中的名称；无要求时传 [] 或 null。",
                "industry": "可多选；必须使用 BOSS 具体细分行业名称，不能传行业组名称或 code。不确定时调用 search_boss_options(field='industry', ...)。",
                "priority": "整数，数值越小越优先；用户未要求时可不传。",
            },
            "allowed_values": allowed_values,
            "important": [
                "不要自行构造任何 BOSS code。",
                "不要创造 allowed_values 中不存在的小型枚举值。",
                "city 和 industry 不确定是否合法时，先调用 search_boss_options，再创建或修改任务。",
                "搜索工具返回的 name 才是 city / industry 应写入任务的语义值。",
            ],
        }

    @agent_tool(
        name="search_boss_options",
        description=(
            "搜索 BOSS 可用的城市或细分行业语义名称。"
            "当 city 或 industry 不确定、用户使用省份/地区/行业大类/近义词时先调用。"
            "返回结果中的 name 才能写入 create_task/update_task；不要自行填写 code。"
        ),
    )
    def search_options(
        self,
        field: SearchOptionField,
        keyword: str,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        query = self._normalize_query(field, keyword)
        if not query:
            raise ValueError("搜索关键词不能为空")
        limit = max(1, min(int(limit), 20))

        matches: list[tuple[int, int, dict[str, str]]] = []
        for index, row in enumerate(self._search_rows[field]):
            name = str(row.get("name") or "").strip()
            if not name or str(row.get("code") or "") == "0":
                continue

            normalized_name = name.casefold()
            group_name = str(row.get("group_name") or "").strip()
            normalized_group = group_name.casefold()
            score = self._match_score(query, normalized_name, normalized_group)
            if score is None:
                continue

            result = {"name": name}
            if field == "industry" and group_name:
                result["group"] = group_name
            matches.append((score, index, result))

        matches.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in matches[:limit]]

    @staticmethod
    def _normalize_query(field: SearchOptionField, keyword: str) -> str:
        query = keyword.strip().casefold()
        if field == "city" and query.endswith("市"):
            query = query[:-1]
        if field == "industry" and query.endswith("行业"):
            query = query[:-2]
        return query.strip()

    @staticmethod
    def _match_score(query: str, name: str, group: str) -> int | None:
        if name == query:
            return 0
        if name.startswith(query):
            return 1
        if query in name:
            return 2
        if group == query:
            return 3
        if group.startswith(query):
            return 4
        if query in group:
            return 5
        return None
