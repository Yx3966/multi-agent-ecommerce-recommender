"""
营销文案Agent
- Prompt模板引擎：基于用户画像动态选择模板(新客/老客/高价值)
- 个性化生成：调用MiniMax M2.7生成文案
- 合规校验：敏感词过滤 + 广告法合规检查
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import get_settings
from models.schemas import (
    MarketingCopyResult,
    Product,
    UserProfile,
    UserSegment,
)

from .base_agent import BaseAgent

PROMPT_TEMPLATES = {
    UserSegment.NEW_USER: """你是电商营销文案专家。为新用户撰写欢迎+推荐文案。
风格要求：热情友好、突出新人专属优惠感、降低决策门槛。
每个商品生成一条文案(30-50字)。""",

    UserSegment.HIGH_VALUE: """你是电商营销文案专家。为高价值VIP用户撰写推荐文案。
风格要求：品质感、尊享感、突出商品高端属性和品牌价值。
每个商品生成一条文案(30-50字)。""",

    UserSegment.PRICE_SENSITIVE: """你是电商营销文案专家。为价格敏感用户撰写推荐文案。
风格要求：突出性价比、促销价格、限时优惠、省钱金额。
每个商品生成一条文案(30-50字)。""",

    UserSegment.ACTIVE: """你是电商营销文案专家。为活跃用户撰写推荐文案。
风格要求：突出商品亮点和使用场景,引发共鸣。
每个商品生成一条文案(30-50字)。""",

    UserSegment.CHURN_RISK: """你是电商营销文案专家。为即将流失的用户撰写召回文案。
风格要求：情感唤回、专属折扣、限时活动、制造紧迫感。
每个商品生成一条文案(30-50字)。""",
}

FORBIDDEN_WORDS = [
    "最好", "第一", "国家级", "全球首", "绝对", "100%",
    "永久", "万能", "祖传", "纯天然",
]

COPY_OUTPUT_INSTRUCTION = """
请以JSON数组格式输出,每个元素格式:
[{"product_id": "xxx", "copy": "文案内容"}]
只输出JSON,不要其他内容。"""


class MarketingCopyAgent(BaseAgent):
    def __init__(self):
        settings = get_settings()
        super().__init__(
            name="marketing_copy",
            timeout=settings.agent_timeout_marketing_copy,
        )
        self.llm = ChatOpenAI(
            api_key=settings.llm_api_key or "missing-api-key",
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0.9,
            max_tokens=2048,
        )

    async def _execute(self, **kwargs: Any) -> MarketingCopyResult:
        user_profile: UserProfile | None = kwargs.get("user_profile")
        products: list[Product] = kwargs.get("products", [])

        if not products:
            return MarketingCopyResult(success=True, copies=[], confidence=1.0)

        template_key = self._select_template(user_profile)
        system_prompt = PROMPT_TEMPLATES[template_key]

        product_info = "\n".join(
            f"- ID:{p.product_id} 名称:{p.name} 类目:{p.category} 价格:¥{p.price} 标签:{','.join(p.tags)}"
            for p in products
        )

        messages = [
            SystemMessage(content=system_prompt + COPY_OUTPUT_INSTRUCTION),
            HumanMessage(content=f"商品列表:\n{product_info}"),
        ]
        response = await self.llm.ainvoke(messages)

        copies = self._parse_copies(response.content)
        copies = [self._compliance_check(c) for c in copies]

        return MarketingCopyResult(
            success=True,
            copies=copies,
            prompt_template_used=template_key.value,
            data={"raw_response": response.content},
            confidence=0.9,
        )

    def _select_template(self, profile: UserProfile | None) -> UserSegment:
        if not profile or not profile.segments:
            return UserSegment.ACTIVE
        priority = [
            UserSegment.NEW_USER,
            UserSegment.HIGH_VALUE,
            UserSegment.CHURN_RISK,
            UserSegment.PRICE_SENSITIVE,
            UserSegment.ACTIVE,
        ]
        for seg in priority:
            if seg in profile.segments:
                return seg
        return UserSegment.ACTIVE

    def _parse_copies(self, raw: str) -> list[dict[str, str]]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            return []

    def _compliance_check(self, copy_item: dict[str, str]) -> dict[str, str]:
        """Filter forbidden advertising words per Chinese Ad Law."""
        text = copy_item.get("copy", "")
        for word in FORBIDDEN_WORDS:
            text = re.sub(re.escape(word), "***", text)
        copy_item["copy"] = text
        return copy_item

