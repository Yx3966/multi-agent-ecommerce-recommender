package com.ecommerce.config;

import com.ecommerce.model.RecommendationRequest;
import com.ecommerce.model.RecommendationResponse;
import com.ecommerce.orchestrator.SupervisorOrchestrator;
import com.ecommerce.service.ABTestService;
import com.ecommerce.service.MemoryService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class RecommendationController {

    private final SupervisorOrchestrator orchestrator;
    private final ABTestService abTestService;
    private final MemoryService memoryService;

    public RecommendationController(
            SupervisorOrchestrator orchestrator,
            ABTestService abTestService,
            MemoryService memoryService
    ) {
        this.orchestrator = orchestrator;
        this.abTestService = abTestService;
        this.memoryService = memoryService;
    }

    @PostMapping("/recommend")
    public RecommendationResponse recommend(@RequestBody RecommendationRequest request) {
        return orchestrator.recommend(request);
    }

    @PostMapping("/memory/behavior")
    public Map<String, Object> recordBehavior(@RequestBody Map<String, Object> body) {
        String userId = String.valueOf(body.get("user_id"));
        String behaviorType = String.valueOf(body.getOrDefault("behavior_type", "view"));
        String itemId = String.valueOf(body.get("item_id"));
        @SuppressWarnings("unchecked")
        Map<String, Object> metadata = (Map<String, Object>) body.getOrDefault("metadata", Map.of());
        return memoryService.recordBehavior(userId, behaviorType, itemId, metadata);
    }

    @GetMapping("/memory/{userId}")
    public Map<String, Object> getUserMemory(@PathVariable String userId) {
        return memoryService.getUserMemory(userId);
    }

    @DeleteMapping("/memory/{userId}")
    public Map<String, Object> forgetUserMemory(@PathVariable String userId) {
        memoryService.forgetUser(userId);
        return Map.of("status", "forgotten", "user_id", userId);
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "healthy", "language", "java", "memory_backend", "memory");
    }

    @GetMapping("/experiments")
    public Map<String, Object> getExperiments() {
        return Map.of(
                "rec_strategy", Map.of(
                        "name", "推荐策略实验",
                        "groups", Map.of("control", "rule_based", "treatment_llm", "llm_rerank")
                )
        );
    }
}
