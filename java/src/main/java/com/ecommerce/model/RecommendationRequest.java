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
public class RecommendationRequest {
    private String userId;
    @Builder.Default
    private String scene = "homepage";
    @Builder.Default
    private int numItems = 10;
    private Map<String, Object> context;
}
