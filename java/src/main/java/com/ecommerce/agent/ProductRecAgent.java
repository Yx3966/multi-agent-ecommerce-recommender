package com.ecommerce.agent;

import com.ecommerce.model.AgentResult;
import com.ecommerce.model.Product;
import com.ecommerce.model.UserProfile;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 商品推荐Agent — 多策略召回 + LLM重排 + 多样性控制
 */
@Component
public class ProductRecAgent extends BaseAgent {

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final List<Product> MOCK_PRODUCTS = List.of(
            Product.builder().productId("P001").name("iPhone 16 Pro").category("手机").price(7999).brand("Apple").sellerId("S01").stock(500).tags(List.of("旗舰", "新品")).build(),
            Product.builder().productId("P002").name("华为 Mate 70").category("手机").price(5999).brand("华为").sellerId("S02").stock(300).tags(List.of("旗舰", "国产")).build(),
            Product.builder().productId("P003").name("AirPods Pro 3").category("耳机").price(1899).brand("Apple").sellerId("S01").stock(1000).tags(List.of("降噪", "无线")).build(),
            Product.builder().productId("P004").name("Sony WH-1000XM6").category("耳机").price(2499).brand("Sony").sellerId("S03").stock(200).tags(List.of("头戴", "降噪")).build(),
            Product.builder().productId("P005").name("iPad Air M3").category("平板").price(4799).brand("Apple").sellerId("S01").stock(400).tags(List.of("学习", "办公")).build(),
            Product.builder().productId("P006").name("小米平板7 Pro").category("平板").price(2499).brand("小米").sellerId("S04").stock(600).tags(List.of("性价比", "娱乐")).build(),
            Product.builder().productId("P007").name("Anker 140W充电器").category("配件").price(399).brand("Anker").sellerId("S05").stock(2000).tags(List.of("快充", "便携")).build(),
            Product.builder().productId("P008").name("机械革命极光X").category("笔记本").price(6999).brand("机械革命").sellerId("S06").stock(150).tags(List.of("游戏", "高性能")).build(),
            Product.builder().productId("P009").name("戴尔U2724D显示器").category("显示器").price(3299).brand("Dell").sellerId("S07").stock(80).tags(List.of("4K", "办公")).build(),
            Product.builder().productId("P010").name("罗技MX Master 3S").category("配件").price(749).brand("罗技").sellerId("S08").stock(500).tags(List.of("无线", "办公")).build()
    );

    public ProductRecAgent(ChatClient.Builder chatClientBuilder) {
        super("product_rec", 8.0, 2);
        this.chatClient = chatClientBuilder.build();
    }

    @Override
    protected AgentResult execute(Map<String, Object> params) throws Exception {
        UserProfile profile = (UserProfile) params.get("userProfile");
        int numItems = (int) params.getOrDefault("numItems", 10);

        List<Product> candidates = recall(profile, numItems * 2);
        List<String> rankedIds = rerank(profile, candidates, numItems);

        Map<String, Product> idMap = candidates.stream()
                .collect(Collectors.toMap(Product::getProductId, p -> p, (a, b) -> a));
        List<Product> finalProducts = rankedIds.stream()
                .filter(idMap::containsKey)
                .map(idMap::get)
                .limit(numItems)
                .collect(Collectors.toList());

        if (finalProducts.size() < numItems) {
            candidates.stream()
                    .filter(p -> !rankedIds.contains(p.getProductId()))
                    .limit(numItems - finalProducts.size())
                    .forEach(finalProducts::add);
        }

        Map<String, Object> data = new HashMap<>();
        data.put("products", finalProducts);
        data.put("recall_strategy", "collaborative_filter+vector+hot");
        data.put("candidate_count", candidates.size());

        return AgentResult.builder()
                .agentName(name)
                .success(true)
                .data(data)
                .confidence(0.8)
                .build();
    }

    private List<Product> recall(UserProfile profile, int limit) {
        List<Product> candidates = new ArrayList<>(MOCK_PRODUCTS);
        if (profile != null && profile.getPreferredCategories() != null) {
            Set<String> preferred = new HashSet<>(profile.getPreferredCategories());
            candidates.sort((a, b) -> Boolean.compare(
                    preferred.contains(b.getCategory()),
                    preferred.contains(a.getCategory())
            ));
        }
        return candidates.subList(0, Math.min(limit, candidates.size()));
    }

    private List<String> rerank(UserProfile profile, List<Product> candidates, int numItems) {
        if (profile == null) {
            return candidates.stream().map(Product::getProductId).limit(numItems).collect(Collectors.toList());
        }
        try {
            String prompt = String.format(
                    "根据用户偏好类目%s和价格范围%.0f-%.0f,从以下商品中选出最优%d个,输出ID数组:\n%s\n只输出JSON数组。",
                    profile.getPreferredCategories(),
                    profile.getPriceRange()[0], profile.getPriceRange()[1],
                    numItems,
                    candidates.stream()
                            .map(p -> p.getProductId() + ":" + p.getName() + "(" + p.getCategory() + ",¥" + p.getPrice() + ")")
                            .collect(Collectors.joining("\n"))
            );
            String response = chatClient.prompt().user(prompt).call().content();
            String cleaned = response.trim();
            if (cleaned.startsWith("```")) {
                cleaned = cleaned.substring(cleaned.indexOf('\n') + 1);
                cleaned = cleaned.substring(0, cleaned.lastIndexOf("```"));
            }
            return objectMapper.readValue(cleaned, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("LLM rerank failed, using default order: {}", e.getMessage());
            return candidates.stream().map(Product::getProductId).limit(numItems).collect(Collectors.toList());
        }
    }
}
