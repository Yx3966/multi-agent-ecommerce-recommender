package com.ecommerce.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentResult {
    private String agentName;
    @Builder.Default
    private boolean success = true;
    @Builder.Default
    private double latencyMs = 0.0;
    private String error;
    private Map<String, Object> data;
    @Builder.Default
    private double confidence = 1.0;
}
