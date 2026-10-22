# 多Agent电商推荐与营销系统 — 项目计划

> 本文记录项目的设计目标、阶段计划和当前状态。项目用于演示 Multi-Agent 推荐系统的工程结构，当前包含 Python 与 Java 两套实现。

---

## 1. 设计目标

构建一个可运行、易理解、可扩展的 Multi-Agent 电商推荐 Demo：

- 用 Supervisor 模式编排 4 个专业 Agent。
- 演示“并行分发 + 聚合”的推荐链路。
- 提供 LLM 结构化输出、失败降级、A/B 实验、实时特征存储等工程组件。
- 保持外部依赖可插拔：未连接 Redis / Milvus / MySQL 时仍可运行主流程。

---

## 2. 参考架构

参考的企业级/开源设计：

- NVIDIA Retail Agentic Commerce：企业级电商 Agent 蓝图。
- Spring AI Alibaba Multi-Agent Demo：Java 生态多 Agent 示例。
- LangGraph 文档：状态图编排与持久化思路。
- 推荐系统经典两阶段架构：召回 + 排序。

---

## 3. 阶段计划

### Phase 1 - Python 核心骨架（已完成）

- FastAPI 入口与请求/响应模型。
- Supervisor 三阶段编排。
- 4 个 Agent 基类与业务实现。
- MiniMax/OpenAI 兼容 LLM 接入。
- LangGraph 状态图第二实现。

### Phase 2 - 特征与存储（部分完成）

- Redis FeatureStore 类已实现。
- Milvus / MySQL 配置与依赖已预留。
- 待完成：启动时注入 Redis client；商品向量离线灌入；库存接真实数据源。

### Phase 3 - A/B 实验与监控（部分完成）

- 一致性哈希分桶。
- Thompson Sampling 后验更新。
- 指标统计与内存 MetricsCollector。
- 待完成：实验配置驱动策略分支；接入 Prometheus。

### Phase 4 - Java 版实现（已完成基础版）

- Spring Boot + Spring AI。
- CompletableFuture 并行编排。
- 与 Python 版同构的 4 个 Agent。
- 待完成：Java 版实验配置、指标与测试补齐。

### Phase 5 - 文档与开源准备（进行中）

- 架构文档、代码导读、项目知识梳理。
- 清理非开源定位内容。
- 待完成：LICENSE、贡献指南、CI、安全策略、Release 流程。

### Phase 6 - 可选扩展

- Go 实现。
- 真实 Milvus 向量召回。
- 真实 WMS / 库存服务接入。
- Human-in-the-loop 审核节点。
- Kubernetes 部署示例。

---

## 4. 当前目录约定

```text
python/   主实现，包含 API、编排、Agent、服务与测试
java/     Spring Boot 等价实现
docs/     架构与代码导读文档
plan.md   项目计划
knowledge.md 项目知识梳理
```

---

## 5. 开源发布前检查项

- [ ] 添加并确认 `LICENSE`。
- [ ] 增加 `CONTRIBUTING.md` 与 `CODE_OF_CONDUCT.md`。
- [ ] 增加 GitHub Actions：Python 测试、Java 构建、Markdown 链接检查。
- [ ] 增加安全说明：API Key 管理、依赖漏洞扫描、Issue 报告渠道。
- [ ] 为 Python 编排链路补充集成测试。
- [ ] 为 Java 版补充单元测试。
- [ ] 明确标注 Mock 数据与未落地的外部集成。

