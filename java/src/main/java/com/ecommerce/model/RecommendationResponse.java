package com.ecommerce.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RecommendationResponse {
    private String requestId;
    private String userId;
    private List<Product> products;
    private List<Map<String, String>> marketingCopies;
    private String experimentGroup;
    private Map<String, AgentResult> agentResults;
    private double totalLatencyMs;
    @Builder.Default
    private Instant timestamp = Instant.now();
}
