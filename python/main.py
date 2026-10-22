"""
Multi-Agent E-Commerce Recommendation System — FastAPI Entry Point

Endpoints:
  POST /api/v1/recommend              - 获取个性化推荐
  POST /api/v1/recommend/graph        - 通过LangGraph pipeline推荐
  POST /api/v1/memory/behavior        - 写入用户行为记忆
  GET  /api/v1/memory/{user_id}       - 查询用户记忆
  DELETE /api/v1/memory/{user_id}     - 删除用户记忆
  GET  /api/v1/experiments            - 查看A/B实验状态
  GET  /api/v1/metrics                - 查看系统监控指标
  GET  /health                        - 健康检查
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from models.schemas import (
    BehaviorEventRequest,
    RecommendationRequest,
    RecommendationResponse,
)
from orchestrator.supervisor import SupervisorOrchestrator
from orchestrator.graph import build_recommendation_graph
from services.ab_test import ABTestEngine
from services.long_term_memory import LongTermMemoryStore
from services.memory import MemoryManager
from services.metrics import MetricsCollector
from services.semantic_memory import EmbeddingProvider, SemanticMemoryStore

logger = structlog.get_logger()
settings = get_settings()


ab_engine = ABTestEngine()
metrics_collector = MetricsCollector()
supervisor = SupervisorOrchestrator(ab_engine=ab_engine)
memory_manager: MemoryManager | None = None
long_term_store: LongTermMemoryStore | None = None
semantic_memory: SemanticMemoryStore | None = None
redis_client: Any = None
rec_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory_manager, long_term_store, semantic_memory, redis_client, rec_graph

    try:
        import redis.asyncio as redis

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("memory.redis_connected", redis_url=settings.redis_url)
    except Exception as exc:
        redis_client = None
        logger.warning("memory.redis_unavailable", error=str(exc))

    long_term_store = LongTermMemoryStore(settings.database_url)
    await long_term_store.init()

    embedding_provider = EmbeddingProvider(settings)
    semantic_memory = SemanticMemoryStore(settings, embedding_provider)
    await semantic_memory.connect()

    memory_manager = MemoryManager(
        redis_client=redis_client,
        ttl=settings.feature_ttl_seconds,
        long_term_store=long_term_store,
        semantic_memory=semantic_memory,
    )
    supervisor.set_memory_manager(memory_manager)
    rec_graph = build_recommendation_graph(
        memory_manager=memory_manager,
        ab_engine=ab_engine,
    )

    logger.info(
        "app.startup",
        model=settings.llm_model,
        memory_backend=memory_manager.backend,
        long_term_backend=memory_manager.long_term_backend,
        semantic_backend=memory_manager.semantic_backend,
    )
    yield

    if semantic_memory:
        await semantic_memory.close()
    if redis_client:
        await redis_client.close()
    logger.info("app.shutdown")


app = FastAPI(
    title="Multi-Agent E-Commerce Recommendation System",
    description="用户画像Agent + 商品推荐Agent + 营销文案Agent + 库存决策Agent，并行+聚合模式",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": settings.llm_model,
        "memory_backend": memory_manager.backend if memory_manager else "not_initialized",
        "long_term_backend": memory_manager.long_term_backend if memory_manager else "not_initialized",
        "semantic_backend": memory_manager.semantic_backend if memory_manager else "not_initialized",
    }


@app.post("/api/v1/recommend", response_model=RecommendationResponse)
async def recommend(request: RecommendationRequest):
    """使用Supervisor编排器进行推荐 (生产推荐用法)"""
    response = await supervisor.recommend(request)
    _collect_metrics(response)
    return response


@app.post("/api/v1/recommend/graph")
async def recommend_via_graph(request: RecommendationRequest):
    """使用LangGraph状态图进行推荐 (展示LangGraph能力)"""
    if not rec_graph:
        return {"error": "Graph not initialized"}
    state = {
        "user_id": request.user_id,
        "scene": request.scene,
        "num_items": request.num_items,
        "context": request.context,
    }
    result = await rec_graph.ainvoke(state)
    return {
        "request_id": result.get("request_id"),
        "user_id": result.get("user_id"),
        "products": [p.model_dump() for p in result.get("final_products", [])],
        "marketing_copies": result.get("marketing_copies", []),
        "experiment_group": result.get("experiment_group", "control"),
        "total_latency_ms": round(result.get("total_latency_ms", 0), 1),
    }


@app.post("/api/v1/memory/behavior")
async def record_behavior(event: BehaviorEventRequest):
    """写入一条用户行为记忆，例如 view/click/purchase/favorite/cart。"""
    if not memory_manager:
        return {"error": "Memory system not initialized"}
    saved = await memory_manager.record_behavior(
        user_id=event.user_id,
        behavior_type=event.behavior_type,
        item_id=event.item_id,
        metadata=event.metadata,
    )
    return {"status": "recorded", "event": saved}


@app.get("/api/v1/memory/{user_id}")
async def get_user_memory(user_id: str):
    """查询某个用户的实时特征、画像快照和最近行为记忆。"""
    if not memory_manager:
        return {"error": "Memory system not initialized"}
    return await memory_manager.get_user_memory(user_id)


@app.delete("/api/v1/memory/{user_id}")
async def forget_user_memory(user_id: str):
    """删除用户记忆，用于隐私删除或测试清理。"""
    if not memory_manager:
        return {"error": "Memory system not initialized"}
    await memory_manager.forget_user(user_id)
    return {"status": "forgotten", "user_id": user_id}


@app.get("/api/v1/experiments")
async def get_experiments():
    """查看所有A/B实验状态"""
    experiments = {}
    for exp_id, exp in ab_engine.experiments.items():
        experiments[exp_id] = {
            "name": exp.name,
            "enabled": exp.enabled,
            "groups": [
                {
                    "name": g.name,
                    "weight": g.weight,
                    "config": g.config,
                    "successes": g.successes,
                    "failures": g.failures,
                }
                for g in exp.groups
            ],
            "stats": ab_engine.get_stats(exp_id),
        }
    return experiments


@app.get("/api/v1/metrics")
async def get_metrics():
    """查看系统监控指标"""
    return {
        "agents": metrics_collector.get_agent_stats(),
        "business": metrics_collector.get_business_stats(),
    }


@app.post("/api/v1/experiments/{experiment_id}/outcome")
async def record_outcome(experiment_id: str, group: str, success: bool):
    """记录A/B测试结果,更新Thompson Sampling"""
    ab_engine.record_outcome(experiment_id, group, success)
    return {"status": "recorded"}


def _collect_metrics(response: RecommendationResponse):
    for name, result in response.agent_results.items():
        metrics_collector.record_agent_call(
            agent_name=name,
            success=result.success,
            latency_ms=result.latency_ms,
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
