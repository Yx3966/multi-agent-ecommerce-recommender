package com.ecommerce.agent;

import com.ecommerce.model.AgentResult;
import com.ecommerce.model.Product;
import com.ecommerce.model.UserProfile;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 营销文案Agent — Prompt模板引擎 + 个性化生成 + 广告法合规校验
 */
@Component
public class MarketingCopyAgent extends BaseAgent {

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final Map<String, String> TEMPLATES = Map.of(
            "new_user", "为新用户撰写欢迎文案,风格热情友好,突出新人优惠。",
            "high_value", "为VIP用户撰写推荐文案,风格品质尊享,突出品牌价值。",
            "price_sensitive", "为价格敏感用户撰写文案,突出性价比和促销优惠。",
            "active", "为活跃用户撰写文案,突出商品亮点和使用场景。",
            "churn_risk", "为流失风险用户撰写召回文案,突出专属折扣。"
    );

    private static final List<String> FORBIDDEN_WORDS = List.of(
            "最好", "第一", "国家级", "全球首", "绝对", "100%", "永久", "万能"
    );

    public MarketingCopyAgent(ChatClient.Builder chatClientBuilder) {
        super("marketing_copy", 10.0, 2);
        this.chatClient = chatClientBuilder.build();
    }

    @Override
    @SuppressWarnings("unchecked")
    protected AgentResult execute(Map<String, Object> params) throws Exception {
        UserProfile profile = (UserProfile) params.get("userProfile");
        List<Product> products = (List<Product>) params.getOrDefault("products", List.of());

        if (products.isEmpty()) {
            return AgentResult.builder().agentName(name).success(true)
                    .data(Map.of("copies", List.of())).confidence(1.0).build();
        }

        String templateKey = selectTemplate(profile);
        String systemPrompt = TEMPLATES.getOrDefault(templateKey, TEMPLATES.get("active"))
                + "\n每个商品生成一条文案(30-50字)。输出JSON数组: [{\"product_id\":\"xxx\",\"copy\":\"文案\"}]";

        String productInfo = products.stream()
                .map(p -> "ID:" + p.getProductId() + " " + p.getName() + " ¥" + p.getPrice() + " " + p.getTags())
                .collect(Collectors.joining("\n"));

        String response = chatClient.prompt()
                .system(systemPrompt)
                .user("商品列表:\n" + productInfo)
                .call()
                .content();

        List<Map<String, String>> copies = parseCopies(response);
        copies = copies.stream().map(this::complianceCheck).collect(Collectors.toList());

        Map<String, Object> data = new HashMap<>();
        data.put("copies", copies);
        data.put("template_used", templateKey);

        return AgentResult.builder()
                .agentName(name)
                .success(true)
                .data(data)
                .confidence(0.9)
                .build();
    }

    private String selectTemplate(UserProfile profile) {
        if (profile == null || profile.getSegments() == null) return "active";
        List<String> priority = List.of("new_user", "high_value", "churn_risk", "price_sensitive", "active");
        for (String seg : priority) {
            if (profile.getSegments().contains(seg)) return seg;
        }
        return "active";
    }

    private List<Map<String, String>> parseCopies(String raw) {
        try {
            String cleaned = raw.trim();
            if (cleaned.startsWith("```")) {
                cleaned = cleaned.substring(cleaned.indexOf('\n') + 1);
                cleaned = cleaned.substring(0, cleaned.lastIndexOf("```"));
            }
            return objectMapper.readValue(cleaned, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Failed to parse copies: {}", e.getMessage());
            return List.of();
        }
    }

    private Map<String, String> complianceCheck(Map<String, String> copyItem) {
        String text = copyItem.getOrDefault("copy", "");
        for (String word : FORBIDDEN_WORDS) {
            text = text.replace(word, "***");
        }
        Map<String, String> result = new HashMap<>(copyItem);
        result.put("copy", text);
        return result;
    }
}
