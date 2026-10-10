from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.domain.global_config import GlobalConfig


@dataclass(frozen=True)
class FilterResult:
    """统一的过滤结果；未通过时携带可记录的原因。"""

    passed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> "FilterResult":
        return cls(True)

    @classmethod
    def reject(cls, reason: str) -> "FilterResult":
        return cls(False, reason)


class BaseJobFilter(ABC):
    """岗位过滤接口：卡片预过滤和详情过滤分成两个阶段。"""

    @abstractmethod
    def check_card(self, card_text: str, config: GlobalConfig) -> FilterResult:
        """未打开详情前，使用卡片文本做轻量过滤。"""

    @abstractmethod
    async def check_detail(
        self,
        detail: dict[str, Any],
        config: GlobalConfig,
        *,
        search_keyword: str = "",
    ) -> FilterResult:
        """获取详情后执行规则和模型过滤。"""
