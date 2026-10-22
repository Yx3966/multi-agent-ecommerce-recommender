# 代码导读

> 按请求链路阅读本项目源码，重点理解 Supervisor 编排、Agent 基类、记忆系统、A/B 引擎与可插拔存储设计。

---

## 1. 推荐入口

### `python/main.py`

FastAPI 入口，提供：

- `POST /api/v1/recommend`：走手写 Supervisor 编排，是主推荐接口。
- `POST /api/v1/recommend/graph`：走 LangGraph 状态图，用于展示状态机式编排。
- `POST /api/v1/memory/behavior`：写入用户行为记忆。
- `GET /api/v1/memory/{user_id}`：查询用户记忆。
- `DELETE /api/v1/memory/{user_id}`：删除用户记忆。
- `GET /api/v1/experiments`：查看实验配置与统计。
- `POST /api/v1/experiments/{id}/outcome`：记录实验 outcome。
- `GET /api/v1/metrics`：查看 Agent 调用指标。
- `GET /health`：健康检查。

启动时通过 lifespan 初始化记忆系统：Redis 可用时使用 Redis，不可用时使用内存降级；然后注入 Supervisor 和 LangGraph。

---

## 2. 核心编排

### `python/orchestrator/supervisor.py`

主流程分三阶段：

1. Phase 1：`user_profile_agent` 与 `product_rec_agent` 并行。
2. Phase 2：带画像的商品重排与库存校验并行。
3. Phase 3：库存过滤后串行生成营销文案。

关键设计：

- 用 `asyncio.gather` 表达无依赖任务的并行。
- 聚合时优先保留“有库存且重排靠前”的商品。
- 如果库存过滤后为空，会降级为重排结果前 N 个，保证响应不为空。
- 推荐完成后会写入 impression 记忆。
- `experiment_group` 会写入响应，但当前还未驱动策略分支。

### `python/orchestrator/graph.py`

同一流程的 LangGraph 表达。图节点是线性的；并行发生在 `parallel_phase1` / `parallel_phase2` 节点内部的 `asyncio.gather`。记忆系统通过 `build_recommendation_graph(memory_manager=...)` 注入。

---

## 3. Agent 基类

### `python/agents/base_agent.py`

模板方法模式：

- 子类实现 `_execute()`。
- 外部调用 `run()`，统一处理计时、重试、失败降级。
- 重试使用 tenacity 指数退避。
- 失败后返回 `success=False` 的降级结果。

注意：`timeout` 字段已定义，但当前没有用 `asyncio.wait_for` 强制执行。

---

## 4. 业务 Agent

### `python/agents/user_profile_agent.py`

- 优先使用 Supervisor/LangGraph 传入的记忆数据。
- 如果没有显式传入，则从 `memory_manager` 获取用户记忆。
- 如果记忆系统不可用，再退化为 FeatureStore 或请求 `context` / 默认样例。
- 通过 System Prompt 约束 LLM 输出 JSON。
- `_parse_profile()` 兼容 ```json 代码块，解析失败时回退为默认 `active` 分群。

### `python/agents/product_rec_agent.py`

- 商品池当前是 `MOCK_PRODUCTS`。
- `_recall()` 根据偏好类目和有库存状态排序候选。
- `_rerank()` 在有画像时调用 LLM 返回商品 ID 顺序；无画像或解析失败时按候选顺序兜底。
- `vector_store` 是 Milvus 扩展点，当前未接入。

### `python/agents/inventory_agent.py`

- 缺货商品直接剔除。
- `stock <= 50` 输出 critical 预警并限购 1 件。
- `stock <= 100` 输出 warning 预警；热销品限购 2 件。
- 热销且库存不超过 300 时限购 3 件。
- 当前库存来自 `Product.stock`，真实 DB/WMS 接口留作扩展。

### `python/agents/marketing_copy_agent.py`

- 按分群优先级选择 Prompt 模板：`new_user > high_value > churn_risk > price_sensitive > active`。
- LLM 输出 JSON 数组，解析失败返回空文案。
- 生成后执行广告法违禁词替换。

---

## 5. 服务层

### `python/services/memory.py`

- 统一管理实时行为记忆、画像快照、推荐曝光记录。
- 有 Redis 时使用 FeatureStore + `profile:{user_id}`；无 Redis 时使用进程内存降级。
- `record_behavior()` 记录 view/click/purchase 等行为。
- `record_impression()` 在推荐完成后记录曝光商品。
- `get_user_memory()` 输出给画像 Agent 的记忆载荷。
- `forget_user()` 支持隐私删除。

### `python/services/feature_store.py`

- Redis Sorted Set 存储行为事件，score 为时间戳。
- 支持 1h / 24h / 7d 滑动窗口。
- 计算 RFM，并支持离线标签合并。
- 当前由 `MemoryManager` 持有和注入。

### `python/services/long_term_memory.py`

- SQLite 长期记忆：画像快照、行为事件流水、长期记忆片段。
- 支持跨重启读取画像快照。
- 支持关键词检索作为语义记忆降级方案。

### `python/services/semantic_memory.py`

- 可选 Milvus 向量记忆。
- 依赖 embedding 服务和 Milvus 连接。
- 不可用时返回空结果，由 MemoryManager 降级到 SQLite 检索。

### `python/services/ab_test.py`

- 一致性分桶：`MD5(user_id:experiment_id)` 取前 8 个 hex 后模 100。
- 按实验组权重映射桶。
- `assign_thompson()` 使用 Beta 分布采样动态分配流量。
- `record_outcome()` 更新后验；`get_stats()` 汇总指标均值、方差、最值。

### `python/services/metrics.py`

内存版指标收集：

- Agent 调用次数、成功率、平均延迟、最近错误。
- 业务事件计数。

生产环境建议替换为 Prometheus。

---

## 6. Java 版对应关系

Java 版位于 `java/src/main/java/com/ecommerce`：

| Python | Java |
|---|---|
| `main.py` | `config/RecommendationController.java` |
| `orchestrator/supervisor.py` | `orchestrator/SupervisorOrchestrator.java` |
| `agents/base_agent.py` | `agent/BaseAgent.java` |
| `agents/*.py` | `agent/*Agent.java` |
| `services/ab_test.py` | `service/ABTestService.java` |
| Pydantic schemas | `model/*.java` + Lombok |

主要差异：

- Java 用 `CompletableFuture.supplyAsync()` 并行，默认走 common pool。
- Java 的 A/B 服务是简版分桶，没有 Thompson Sampling。
- Java 版提供 MemoryService 进程内记忆；暂无 MetricsCollector 和 LangGraph 等价物。

---

## 7. 建议阅读顺序

1. `README.md`
2. `python/main.py`
3. `python/services/memory.py`
4. `python/services/long_term_memory.py`
5. `python/orchestrator/supervisor.py`
6. `python/agents/base_agent.py`
7. 四个业务 Agent
8. `python/services/ab_test.py`
9. `python/services/feature_store.py`
10. `python/orchestrator/graph.py`
11. Java 版对应类
