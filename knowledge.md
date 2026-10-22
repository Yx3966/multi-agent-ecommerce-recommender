# 多Agent电商推荐与营销系统 — 项目知识梳理

> 本文基于当前仓库源码与文档整理，记录项目定位、技术栈、核心流程、实现现状与后续补齐建议。

---

## 1. 项目定位

这是一个用于学习和演示的 Multi-Agent 电商推荐系统。核心目标是展示一套“AI 运营团队”式协同架构：

- **用户画像 Agent**：生成用户分群、偏好类目、价格区间、RFM 分、实时标签。
- **商品推荐 Agent**：负责候选商品召回，并在拿到画像后做 LLM 重排。
- **库存决策 Agent**：过滤无货商品，输出低库存预警和限购策略。
- **营销文案 Agent**：按用户分群选择 Prompt 模板，生成个性化商品文案，并做广告法违禁词过滤。
- **Supervisor 编排器**：把以上 Agent 编排成“并行分发 + 聚合”的三阶段流水线。

它重点回答传统推荐的三个问题：

| 传统痛点 | 本项目方案 |
|---|---|
| 推荐了缺货商品 | 库存 Agent 实时校验，缺货剔除 |
| 文案千人一面 | 文案 Agent 按用户分群选择模板并生成个性化文案 |
| 推荐/文案/库存系统割裂 | Supervisor 统一编排，结果聚合后返回 |

需要注意：当前代码是可运行的架构演示级实现。核心编排、A/B 引擎、Redis 特征存储代码是真实的；但商品库是 Mock 数据，商品向量检索/MySQL/WMS 等集成仍保留接口；Milvus 同时可作为可选长期语义记忆后端，默认不依赖真实中间件也能演示主流程。

当前仓库包含：

- `python/`：功能最完整，包含 FastAPI、Supervisor、LangGraph、A/B、Feature Store、Metrics、单测。
- `java/`：Spring Boot + Spring AI 的等价基础实现，编排逻辑与 Python 版基本同构。
- Go 实现当前未包含，可作为后续扩展。

---

## 2. 技术栈

### Python 版

| 层 | 技术 |
|---|---|
| Web 服务 | FastAPI + Uvicorn |
| 数据模型 | Pydantic v2 |
| 配置 | pydantic-settings，环境变量前缀 `ECOM_` |
| LLM 客户端 | LangChain `ChatOpenAI`，默认接 MiniMax OpenAI 兼容接口 |
| Agent 编排 | 手写 `asyncio.gather` Supervisor + LangGraph `StateGraph` 双实现 |
| 重试 | tenacity，指数退避 |
| 日志 | structlog |
| A/B 实验 | 自研分桶引擎 + numpy Beta 分布 Thompson Sampling |
| 短期特征 | Redis Sorted Set 滑动窗口；由 MemoryManager 注入，Redis 不可用时走内存降级 |
| 长期记忆 | SQLite 持久化画像快照/行为事件/记忆片段；Milvus 可选语义检索 |
| 向量库 | `pymilvus` 依赖已引入，代码中仅预留 `vector_store` 接口 |
| 业务库 | SQLAlchemy/SQLite 配置存在，默认未真正使用 |
| 监控 | 内存版 MetricsCollector，可替换为 Prometheus |

### Java 版

| 层 | 技术 |
|---|---|
| Web 服务 | Spring Boot 3.4 |
| LLM 客户端 | Spring AI `ChatClient` |
| 并行模型 | `CompletableFuture.supplyAsync()` |
| 数据模型 | Lombok |
| JSON | Jackson |
| 数据访问 | Spring Data JPA，默认 H2 |
| A/B 实验 | 简版 MD5 分桶 |
| 记忆系统 | MemoryService 进程内记忆，支持行为/画像快照/曝光/遗忘 |

### 基础设施

`docker-compose.yml` 定义 4 个服务：

- `api`：Python FastAPI，端口 `8000`。
- `redis`：Redis 7，作为 Feature Store。
- `milvus`：Milvus v2.4 standalone，可作为商品向量库和可选长期语义记忆后端。
- `mysql`：MySQL 8，作为业务库预留；Python 默认配置实际仍指向 SQLite。

---

## 3. 完整请求流程

### Python 主流程：`POST /api/v1/recommend`

1. FastAPI 接收 `RecommendationRequest`。
2. Supervisor 生成 `request_id`，调用 A/B 引擎完成一致性分桶。
3. Phase 1：用户画像与商品召回并行。
4. Phase 2：带画像的商品重排与库存校验并行。
5. 聚合：按库存可用 ID 过滤商品，截断到 `num_items`；为空时降级为重排结果前 N 个。
6. Phase 3：基于最终商品列表生成营销文案，并做违禁词过滤。
7. 返回商品、文案、实验分组、各 Agent 诊断信息和总延迟，同时写入指标。

### LangGraph 流程：`POST /api/v1/recommend/graph`

```text
init
  -> parallel_phase1(user_profile + product_recall)
  -> parallel_phase2(rerank + inventory)
  -> filter
  -> marketing_copy
  -> aggregate
  -> END
```

图本身是线性节点；真正并行发生在 `parallel_phase1/parallel_phase2` 节点内部的 `asyncio.gather`。

### Java 流程

Java 版在 `SupervisorOrchestrator.recommend()` 中复刻同一流程，使用 `CompletableFuture` 并行。差异点：Java 商品召回数量是 `numItems * 2`，A/B 服务更简化，默认使用 common pool。

---

## 4. Agent 实现要点

### BaseAgent

- 模板方法模式：子类实现 `_execute()`，外部调用 `run()`。
- Python 使用 tenacity 指数退避重试。
- Java 使用循环重试 + 阻塞 sleep。
- 失败后返回降级结果。
- Python 版 timeout 字段已定义，但未强制执行。

### UserProfileAgent

- 通过 System Prompt 约束 LLM 输出固定 JSON。
- 优先使用请求显式传入的记忆；否则从 MemoryManager 获取实时行为、画像快照和请求上下文；记忆系统不可用时再退化为请求 context 或内置样例。
- 对 LLM 输出做代码块清理和 JSON 容错解析。

### ProductRecAgent

- 当前商品池是 Mock 数据。
- 召回阶段根据偏好类目与库存状态排序。
- 有画像时调用 LLM 重排；无画像或解析失败时按候选顺序兜底。
- Milvus 检索是预留扩展点。

### InventoryAgent

- `stock <= 0`：不可推荐。
- `stock <= 50`：critical，限购 1 件。
- `50 < stock <= 100`：warning；热销品限购 2 件。
- 热销且 `stock <= 300`：限购 3 件。
- 当前库存来自 `Product.stock`。

### MarketingCopyAgent

- 模板优先级：`new_user > high_value > churn_risk > price_sensitive > active`。
- 输出格式要求 JSON 数组。
- 生成后执行广告法违禁词替换。

---

## 5. 服务层

### 记忆系统

- `MemoryManager` 统一管理工作记忆、行为记忆、画像快照和推荐曝光记忆。
- 有 Redis 时使用 Sorted Set 滑动窗口 + `profile:{user_id}` 快照；无 Redis 时使用进程内存降级。
- 支持行为写入、用户记忆查询、用户记忆删除。
- 推荐完成后会记录 impression，用于后续请求理解用户最近被推荐了哪些商品。

### LongTermMemoryStore

- SQLite 持久化 `user_profiles`、`behavior_events`、`memory_episodes`。
- 画像快照长期保存，行为事件可追溯，记忆片段支持关键词检索。
- 支持 `delete_user()` 做隐私删除。

### SemanticMemoryStore

- 可选 Milvus 向量记忆，默认关闭。
- 需要配置 embedding 模型并连接 Milvus 后启用。
- 不可用时自动降级为 SQLite 关键词检索。

### A/B 测试引擎

- 一致性分桶：`MD5(user_id:experiment_id)` 取前 8 个 hex 后模 100。
- 支持按权重分配实验组。
- 支持 Thompson Sampling 后验更新。
- 支持指标记录与统计。

现状：Supervisor 只调用 `assign()`，并把分组写入响应；实验配置尚未驱动重排/文案策略分支，`assign_thompson()` 也未接入主链路。

### FeatureStore

- Redis Sorted Set 存储行为事件，score 为时间戳。
- 支持 1h / 24h / 7d 滑动窗口。
- 支持 RFM 计算与离线标签合并。

现状：已接入启动流程；有 Redis 时使用 Redis，无 Redis 时使用内存降级。推荐完成后会记录曝光记忆，并提供行为写入、查询和遗忘接口。

### MetricsCollector

- 记录 Agent 调用次数、成功率、平均延迟、最近错误。
- 记录业务事件。
- 内存实现，进程重启丢失。

---

## 6. API 与启动方式

### Python API

默认端口 `8000`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/memory/behavior` | 写入用户行为记忆 |
| GET | `/api/v1/memory/{user_id}` | 查询用户记忆 |
| DELETE | `/api/v1/memory/{user_id}` | 删除用户记忆 |
| POST | `/api/v1/recommend` | 主推荐接口 |
| POST | `/api/v1/recommend/graph` | LangGraph 版推荐 |
| GET | `/api/v1/experiments` | 查看实验配置和统计 |
| POST | `/api/v1/experiments/{experiment_id}/outcome` | 记录实验 outcome |
| GET | `/api/v1/metrics` | 查看 Agent/业务指标 |

启动：

```powershell
cd python
pip install -r requirements.txt
copy .env.example .env
python main.py
```

没有 LLM API Key 时，系统仍能部分降级运行：商品召回使用 Mock 数据，画像/文案 Agent 会失败降级。

### Java API

默认端口 `8080`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/recommend` | Java 版推荐 |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/memory/behavior` | 写入用户行为记忆 |
| GET | `/api/v1/memory/{userId}` | 查询用户记忆 |
| DELETE | `/api/v1/memory/{userId}` | 删除用户记忆 |
| GET | `/api/v1/experiments` | 返回实验信息 |

启动：

```powershell
cd java
mvn spring-boot:run
```

### Docker

```powershell
docker compose up --build
```

---

## 7. 测试现状

已有测试包括 `python/tests/test_ab_test.py` 和 `python/tests/test_memory.py`，覆盖：

- 同一用户分组一致性。
- 大样本分桶分布大致均衡。
- Thompson Sampling 后验更新。
- 自定义实验注册与分配。
- 指标记录与统计。
- 记忆系统本地模式的行为写入、画像快照更新、曝光记录和用户遗忘。
- SQLite 长期记忆的跨实例持久化、关键词检索和用户遗忘。

未覆盖：

- Supervisor 编排流程。
- LLM 解析容错。
- 库存过滤与限购规则。
- 文案合规过滤。
- Java 版测试。

---

## 8. 当前完成度评估

### 已真实落地

- Supervisor 三阶段并行编排，Python/Java 双语言同构。
- Agent 基类：重试、失败降级、错误率统计。
- 4 个 Agent 的 LLM 调用与 JSON 输出容错解析。
- 营销文案分群模板与广告法违禁词过滤。
- A/B 一致性分桶、Thompson Sampling、指标统计、单元测试。
- MemoryManager + Redis FeatureStore + SQLite LongTermMemoryStore 的分层记忆系统，支持可选 Milvus 语义记忆。
- FastAPI/Spring Boot 双服务入口。
- Docker Compose 基础设施编排。

### 仍是占位或半落地

1. 商品召回是 Mock，没有真实协同过滤/向量检索。
2. 语义记忆默认关闭，依赖外部 embedding 服务和 Milvus；生产开启前需要评估成本与延迟。
3. 库存不查真实 DB/WMS，只读 `Product.stock`。
4. Python Agent 定义了 timeout，但未强制执行超时。
5. 熔断规则只在 `docs/architecture.md` 中描述，代码没有实现。
6. A/B 分组未驱动策略分支，只体现在响应字段。
7. `assign_thompson()` 未被编排链路使用。
8. Java 版 A/B 是硬编码简版，无 Thompson、无实验配置驱动；Java 记忆系统当前为进程内存实现，重启丢失。
9. LangGraph 版的并行是节点内部 `asyncio.gather` 模拟。
10. Java `BaseAgent` 日志格式使用了 `{:.1f}`，SLF4J 实际只识别 `{}`。

---

## 9. 建议补齐优先级

1. 完善记忆闭环：推荐反馈自动更新长期兴趣，补充跨进程会话记忆和长期语义记忆。
2. 让实验配置生效：Supervisor 根据 `experiment.config.rerank` 选择规则重排或 LLM 重排。
3. 强制 Agent 超时：Python 用 `asyncio.wait_for`，Java 用超时版 CompletableFuture。
4. 接真实 Milvus 召回：离线生成商品 embedding，运行时向量召回。
5. 库存接 DB/WMS：至少用 SQLite/MySQL 表替代 `Product.stock` 直读。
6. 补集成测试：无 LLM 时用 Fake LLM/Mock ChatClient 测 Supervisor 全链路。
7. 开源前补齐 LICENSE、贡献指南、CI、安全策略和 Release 流程。

---

## 10. 一句话总结

这个项目的核心价值是清晰展示 Multi-Agent 推荐系统的工程骨架：Supervisor 负责依赖分析和三阶段并行编排，四个 Agent 分别处理画像、召回/重排、库存、文案，外围再配上 A/B 实验、特征存储、指标和降级容错。它当前更适合作为架构学习和开源演示项目；距离生产系统还差真实数据源接入、超时/熔断强制执行、实验策略闭环和更完整的测试。
