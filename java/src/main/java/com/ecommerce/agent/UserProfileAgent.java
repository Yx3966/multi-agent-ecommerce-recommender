package com.ecommerce.agent;

import com.ecommerce.model.AgentResult;
import com.ecommerce.model.UserProfile;
import com.ecommerce.service.MemoryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 用户画像Agent — 实时特征提取 + RFM模型 + 用户分群
 */
@Component
public class UserProfileAgent extends BaseAgent {

    private final ChatClient chatClient;
    private final MemoryService memoryService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final String SYSTEM_PROMPT = """
            你是一个电商用户画像分析专家。根据用户的行为数据和画像快照,分析用户特征并生成画像。
            输出JSON格式:
            {"segments":["active"],"preferred_categories":["手机"],"price_range":[0,10000],
             "rfm_score":{"recency":0.8,"frequency":0.5,"monetary":0.6},
             "real_time_tags":{"活跃时段":"晚间"}}
            只输出JSON。""";

    public UserProfileAgent(ChatClient.Builder chatClientBuilder, MemoryService memoryService) {
        super("user_profile", 5.0, 2);
        this.chatClient = chatClientBuilder.build();
        this.memoryService = memoryService;
    }

    @Override
    protected AgentResult execute(Map<String, Object> params) throws Exception {
        String userId = (String) params.get("userId");
        Map<String, Object> behavior = collectBehavior(userId, params);

        String response = chatClient.prompt()
                .system(SYSTEM_PROMPT)
                .user("用户ID: " + userId + "\n记忆数据: " + objectMapper.writeValueAsString(behavior))
                .call()
                .content();

        UserProfile profile = parseProfile(userId, response);

        Map<String, Object> data = new HashMap<>();
        data.put("raw_analysis", response);
        data.put("profile", profile);
        data.put("memory_backend", behavior.getOrDefault("memory_backend", "memory"));

        return AgentResult.builder()
                .agentName(name)
                .success(true)
                .data(data)
                .confidence(0.85)
                .build();
    }

    private Map<String, Object> collectBehavior(String userId, Map<String, Object> params) {
        return memoryService.getUserMemory(userId);
    }

    @SuppressWarnings("unchecked")
    private UserProfile parseProfile(String userId, String raw) {
        try {
            String cleaned = raw.trim();
            if (cleaned.startsWith("```")) {
                cleaned = cleaned.substring(cleaned.indexOf('\n') + 1);
                cleaned = cleaned.substring(0, cleaned.lastIndexOf("```"));
            }
            Map<String, Object> data = objectMapper.readValue(cleaned, Map.class);

            List<String> segments = (List<String>) data.getOrDefault("segments", List.of("active"));
            List<String> categories = (List<String>) data.getOrDefault("preferred_categories", List.of());
            List<?> priceRaw = (List<?>) data.getOrDefault("price_range", List.of(0, 10000));
            Map<String, Double> rfm = (Map<String, Double>) data.getOrDefault("rfm_score", Map.of());
            Map<String, Object> tags = (Map<String, Object>) data.getOrDefault("real_time_tags", Map.of());

            return UserProfile.builder()
                    .userId(userId)
                    .segments(segments)
                    .preferredCategories(categories)
                    .priceRange(new double[]{
                            ((Number) priceRaw.get(0)).doubleValue(),
                            priceRaw.size() > 1 ? ((Number) priceRaw.get(1)).doubleValue() : 10000
                    })
                    .rfmScore(rfm)
                    .realTimeTags(tags)
                    .build();
        } catch (Exception e) {
            log.warn("Failed to parse profile for {}: {}", userId, e.getMessage());
            return UserProfile.builder()
                    .userId(userId)
                    .segments(List.of("active"))
                    .build();
        }
    }
}
