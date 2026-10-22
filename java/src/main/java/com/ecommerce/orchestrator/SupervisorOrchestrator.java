package com.ecommerce.orchestrator;

import com.ecommerce.agent.InventoryAgent;
import com.ecommerce.agent.MarketingCopyAgent;
import com.ecommerce.agent.ProductRecAgent;
import com.ecommerce.agent.UserProfileAgent;
import com.ecommerce.model.AgentResult;
import com.ecommerce.model.Product;
import com.ecommerce.model.RecommendationRequest;
import com.ecommerce.model.RecommendationResponse;
import com.ecommerce.model.UserProfile;
import com.ecommerce.service.ABTestService;
import com.ecommerce.service.MemoryService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Supervisor编排器 — 并行分发 + 聚合模式 (Java CompletableFuture实现)
 */
@Service
public class SupervisorOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(SupervisorOrchestrator.class);

    private final UserProfileAgent userProfileAgent;
    private final ProductRecAgent productRecAgent;
    private final MarketingCopyAgent marketingCopyAgent;
    private final InventoryAgent inventoryAgent;
    private final ABTestService abTestService;
    private final MemoryService memoryService;

    public SupervisorOrchestrator(
            UserProfileAgent userProfileAgent,
            ProductRecAgent productRecAgent,
            MarketingCopyAgent marketingCopyAgent,
            InventoryAgent inventoryAgent,
            ABTestService abTestService,
            MemoryService memoryService) {
        this.userProfileAgent = userProfileAgent;
        this.productRecAgent = productRecAgent;
        this.marketingCopyAgent = marketingCopyAgent;
        this.inventoryAgent = inventoryAgent;
        this.abTestService = abTestService;
        this.memoryService = memoryService;
    }

    public RecommendationResponse recommend(RecommendationRequest request) {
        String requestId = UUID.randomUUID().toString();
        long start = System.nanoTime();
        Map<String, AgentResult> agentResults = new HashMap<>();

        log.info("[Supervisor] start request={} user={}", requestId, request.getUserId());

        String experimentGroup = abTestService.assign(request.getUserId()).getOrDefault("group", "control").toString();

        // Phase 1: parallel — user profile + product recall
        CompletableFuture<AgentResult> profileFuture = userProfileAgent.runAsync(
                Map.of("userId", request.getUserId()));
        CompletableFuture<AgentResult> recFuture = productRecAgent.runAsync(
                Map.of("numItems", request.getNumItems() * 2));

        AgentResult profileResult = profileFuture.join();
        AgentResult recResult = recFuture.join();
        agentResults.put("user_profile", profileResult);
        agentResults.put("product_recall", recResult);

        UserProfile profile = profileResult.getData() != null
                ? (UserProfile) profileResult.getData().get("profile") : null;
        @SuppressWarnings("unchecked")
        List<Product> rawProducts = recResult.getData() != null
                ? (List<Product>) recResult.getData().get("products") : List.of();

        // Phase 2: parallel — rerank + inventory check
        CompletableFuture<AgentResult> rerankFuture = productRecAgent.runAsync(
                Map.of("userProfile", profile != null ? profile : new UserProfile(),
                       "numItems", request.getNumItems()));
        CompletableFuture<AgentResult> inventoryFuture = inventoryAgent.runAsync(
                Map.of("products", rawProducts));

        AgentResult rerankResult = rerankFuture.join();
        AgentResult inventoryResult = inventoryFuture.join();
        agentResults.put("rerank", rerankResult);
        agentResults.put("inventory", inventoryResult);

        @SuppressWarnings("unchecked")
        List<Product> rankedProducts = rerankResult.getData() != null
                ? (List<Product>) rerankResult.getData().get("products") : rawProducts;
        @SuppressWarnings("unchecked")
        List<String> availableIds = inventoryResult.getData() != null
                ? (List<String>) inventoryResult.getData().get("available_products") : List.of();

        Set<String> availSet = new HashSet<>(availableIds);
        List<Product> finalProducts = rankedProducts.stream()
                .filter(p -> availSet.contains(p.getProductId()))
                .limit(request.getNumItems())
                .collect(Collectors.toList());
        if (finalProducts.isEmpty()) {
            finalProducts = rankedProducts.stream().limit(request.getNumItems()).collect(Collectors.toList());
        }

        // Phase 3: marketing copy
        AgentResult copyResult = marketingCopyAgent.runAsync(
                Map.of("userProfile", profile != null ? profile : new UserProfile(),
                       "products", finalProducts))
                .join();
        agentResults.put("marketing_copy", copyResult);

        @SuppressWarnings("unchecked")
        List<Map<String, String>> copies = copyResult.getData() != null
                ? (List<Map<String, String>>) copyResult.getData().get("copies") : List.of();

        double totalLatency = (System.nanoTime() - start) / 1_000_000.0;
        log.info("[Supervisor] complete request={} latency={}ms products={}", requestId, totalLatency, finalProducts.size());

        RecommendationResponse response = RecommendationResponse.builder()
                .requestId(requestId)
                .userId(request.getUserId())
                .products(finalProducts)
                .marketingCopies(copies)
                .experimentGroup(experimentGroup)
                .agentResults(agentResults)
                .totalLatencyMs(totalLatency)
                .build();

        try {
            memoryService.recordImpression(
                    request.getUserId(),
                    finalProducts,
                    requestId,
                    request.getScene(),
                    experimentGroup
            );
        } catch (Exception e) {
            log.warn("[Memory] record impression failed: {}", e.getMessage());
        }

        return response;
    }
}
