"""
监控指标收集
- Agent调用成功率 / 延迟
- 推荐CTR / CVR / GMV
- A/B测试实验指标
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMetric:
    call_count: int = 0
    success_count: int = 0
    total_latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.call_count if self.call_count else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.call_count if self.call_count else 0.0


class MetricsCollector:
    """In-memory metrics collector; swap to Prometheus in production."""

    def __init__(self):
        self._agent_metrics: dict[str, AgentMetric] = defaultdict(AgentMetric)
        self._business_events: list[dict[str, Any]] = []

    def record_agent_call(self, agent_name: str, success: bool, latency_ms: float, error: str = ""):
        m = self._agent_metrics[agent_name]
        m.call_count += 1
        if success:
            m.success_count += 1
        m.total_latency_ms += latency_ms
        if error:
            m.errors.append(error)

    def record_business_event(self, event_type: str, **kwargs: Any):
        """Record CTR/CVR/GMV events for analytics."""
        self._business_events.append({
            "type": event_type,
            "timestamp": time.time(),
            **kwargs,
        })

    def get_agent_stats(self) -> dict[str, dict[str, Any]]:
        result = {}
        for name, m in self._agent_metrics.items():
            result[name] = {
                "call_count": m.call_count,
                "success_rate": round(m.success_rate, 4),
                "avg_latency_ms": round(m.avg_latency_ms, 1),
                "recent_errors": m.errors[-5:],
            }
        return result

    def get_business_stats(self) -> dict[str, Any]:
        if not self._business_events:
            return {}
        by_type: dict[str, list[dict]] = defaultdict(list)
        for e in self._business_events:
            by_type[e["type"]].append(e)
        stats = {}
        for t, events in by_type.items():
            stats[t] = {"count": len(events)}
        return stats
