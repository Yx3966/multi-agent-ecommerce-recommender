# 多Agent电商推荐与营销系统

一个用于学习和演示 Multi-Agent 架构的电商推荐项目。系统用 1 个 Supervisor 编排 4 个专业 Agent，完成从用户理解、商品召回/重排、库存校验到个性化营销文案生成的完整链路。

> 当前实现定位：可运行的架构演示项目。商品目录默认使用 Mock 数据；Redis / Milvus / MySQL 等外部依赖以可插拔方式预留，未连接时会走降级路径。

---

## 核心能力

- **Supervisor 并行编排**：画像与召回并行，重排与库存并行，文案生成串行收尾。
- **用户画像 Agent**：基于记忆数据、请求上下文和 LLM 结构化输出生成用户分群、偏好类目、价格区间、RFM 与实时标签。
- **商品推荐 Agent**：候选召回 + LLM 重排，解析失败自动回退到候选顺序。
- **库存决策 Agent**：缺货过滤、低库存预警、按库存深度和商品热度计算限购策略。
- **营销文案 Agent**：按用户分群选择 Prompt 模板，生成商品文案，并做广告法违禁词过滤。
- **A/B 实验引擎**：一致性哈希分桶、权重分配、Thompson Sampling 后验更新、指标统计。
- **实时特征存储**：Redis Sorted Set 滑动窗口行为序列，支持 1h / 24h / 7d 特征聚合与 RFM 计算。
- **分层记忆系统**：请求内工作记忆、用户行为记忆、画像快照、推荐曝光记忆和实验后验记忆；无 Redis 时自动使用内存模式。
- **双语言实现**：Python 版功能最完整；Java 版提供 Spring Boot + Spring AI 的同构实现。

---

## 系统架构

```text
用户请求
  │
  ▼
Supervisor
  ├─ Phase 1: 用户画像 Agent  ∥ 商品召回 Agent
  ├─ Phase 2: LLM 重排       ∥ 库存决策 Agent
  ├─ Aggregate: 库存过滤 + 截断 + 兜底
  └─ Phase 3: 营销文案 Agent
        │
        ▼
RecommendationResponse
```

依赖关系：

- 画像与初始召回互不依赖，所以并行。
- 重排依赖画像，库存校验依赖候选商品；重排与库存互不依赖，所以并行。
- 文案依赖最终商品列表，所以在聚合后串行执行。

---

## 记忆系统

记忆系统分为五层：

1. **请求内工作记忆**：由 Supervisor / LangGraph State 保存本次请求的中间结果。
2. **实时行为记忆**：`view/click/purchase/favorite/cart/impression` 写入 Redis Sorted Set；无 Redis 时写入内存。
3. **长期画像记忆**：SQLite 持久化画像快照、行为事件流水和长期记忆片段。
4. **长期语义记忆**：可选 Milvus 向量检索；未开启或未连接时降级为 SQLite 关键词检索。
5. **实验记忆**：A/B 引擎保存分组、指标和 Thompson Sampling 后验。

推荐完成后会自动记录 `impression`，下一次推荐可以感知用户最近被推荐了哪些商品。

---

## 项目结构

```text
.
├── README.md
├── plan.md
├── docker-compose.yml
├── knowledge.md
├── docs/
│   ├── architecture.md
│   ├── code-walkthrough.md
│   └── project-plan.md
├── python/
│   ├── main.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env.example
│   ├── agents/
│   ├── orchestrator/
│   ├── services/
│   ├── models/
│   ├── config/
│   └── tests/
└── java/
    ├── pom.xml
    └── src/main/
```

---

## 技术栈

### Python

- FastAPI / Uvicorn
- Pydantic v2 / pydantic-settings
- LangChain `ChatOpenAI` / LangGraph
- tenacity / structlog / numpy
- Redis / SQLite 长期记忆 / pymilvus 可选语义记忆

### Java

- Java 17
- Spring Boot 3.4
- Spring AI OpenAI Starter
- CompletableFuture 并行编排
- Lombok / Jackson / H2 / MySQL Connector
- MemoryService 进程内记忆（行为事件 / 画像快照 / 推荐曝光）

### 基础设施

- Docker Compose
- Redis：Feature Store / 用户记忆
- Milvus：商品向量检索预留，也可作为可选长期语义记忆后端
- MySQL：业务数据预留

---

## 快速开始

### 方式一：运行 Python 版

```powershell
cd python
pip install -r requirements.txt
copy .env.example .env
```

编辑 `python/.env`，填入 LLM 配置：

```env
ECOM_LLM_API_KEY=your_api_key_here
ECOM_LLM_BASE_URL=https://api.minimax.chat/v1
ECOM_LLM_MODEL=MiniMax-M1
ECOM_SEMANTIC_MEMORY_ENABLED=false
ECOM_EMBEDDING_MODEL=
```

启动：

```powershell
python main.py
```

服务默认监听 `http://localhost:8000`。

> 没有配置 LLM API Key 时，系统仍可部分运行：商品召回使用 Mock 数据，画像/文案 Agent 会失败并降级，最终响应中的画像和文案可能为空。

### 方式二：运行 Java 版

```powershell
cd java
mvn spring-boot:run
```

服务默认监听 `http://localhost:8080`。

### 方式三：Docker Compose

```powershell
docker compose up --build
```

Compose 会启动：

- Python API：`8000`
- Redis：`6379`
- Milvus：`19530` / `9091`
- MySQL：`3306`

当前代码默认不会强制依赖 Redis / Milvus / MySQL；未接入时使用内置降级逻辑。

---

## API 示例

### 获取推荐

```powershell
curl -X POST http://localhost:8000/api/v1/recommend `
  -H "Content-Type: application/json" `
  -d '{"user_id":"u001","scene":"homepage","num_items":5,"context":{"recent_views":["手机","耳机"]}}'
```

### LangGraph 版本

```powershell
curl -X POST http://localhost:8000/api/v1/recommend/graph `
  -H "Content-Type: application/json" `
  -d '{"user_id":"u001","scene":"homepage","num_items":5}'
```

### 写入用户行为记忆

```powershell
curl -X POST http://localhost:8000/api/v1/memory/behavior `
  -H "Content-Type: application/json" `
  -d '{"user_id":"u001","behavior_type":"purchase","item_id":"P003","metadata":{"category":"耳机","price":1899,"amount":1899}}'
```

### 查询用户记忆

```powershell
curl http://localhost:8000/api/v1/memory/u001
```

### 删除用户记忆

```powershell
curl -X DELETE http://localhost:8000/api/v1/memory/u001
```

### 查看实验状态

```powershell
curl http://localhost:8000/api/v1/experiments
```

### 查看运行指标

```powershell
curl http://localhost:8000/api/v1/metrics
```

---

## 文档

- [架构设计](docs/architecture.md)
- [代码导读](docs/code-walkthrough.md)
- [项目计划](docs/project-plan.md)
- [项目知识梳理](knowledge.md)

---

## 当前限制

- 商品目录是 Mock 数据，未接入真实商品库。
- Milvus 向量检索只保留扩展点，未实际执行 ANN 召回。
- 短期记忆默认使用内存模式，配置 Redis 后自动切换；长期记忆默认使用 SQLite，Milvus 语义检索默认关闭。
- 库存校验使用商品对象中的 `stock` 字段，未接入真实 WMS / DB。
- Agent timeout 已配置，但 Python 版未用 `asyncio.wait_for` 强制执行。
- 熔断规则目前只体现在架构文档中，代码未实现。
- A/B 分组会写入响应，但实验配置尚未驱动推荐策略分支。
- 仓库当前包含 Python / Java 实现；Go 实现可作为后续扩展。

---

## Roadmap

1. 补充推荐反馈后的长期兴趣更新闭环，并完善跨进程会话记忆。
2. 让 A/B 实验配置真正驱动重排策略、文案模板和模型参数。
3. 强制执行 Agent 超时，并补充熔断器实现。
4. 接入真实 Milvus 商品向量召回。
5. 用真实库存表或 WMS 接口替换 `Product.stock` 直读。
6. 补充 Supervisor 全链路集成测试与 Java 版测试。
7. 增加 CI、Lint、Release 与容器镜像发布流程。

---

## License

计划以 MIT License 开源。正式发布前请确认根目录已添加 `LICENSE` 文件，并核对作者、版权年份和第三方依赖许可证。
