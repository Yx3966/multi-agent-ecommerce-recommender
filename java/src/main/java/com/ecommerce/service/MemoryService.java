package com.ecommerce.service;

import com.ecommerce.model.Product;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.stream.Collectors;

/**
 * Java 版记忆服务。
 *
 * 当前实现为进程内存模式，职责与 Python MemoryManager 对齐：
 * - 行为记忆：view/click/purchase/favorite/cart/impression
 * - 画像快照：行为计数、类目偏好、购买金额、最近推荐
 * - 隐私删除：forgetUser
 */
@Service
public class MemoryService {

    private final Map<String, List<Map<String, Object>>> events = new ConcurrentHashMap<>();
    private final Map<String, Map<String, Object>> profiles = new ConcurrentHashMap<>();

    public Map<String, Object> recordBehavior(
            String userId,
            String behaviorType,
            String itemId,
            Map<String, Object> metadata
    ) {
        Map<String, Object> event = new HashMap<>();
        event.put("user_id", userId);
        event.put("behavior_type", behaviorType);
        event.put("item_id", itemId);
        event.put("ts", nowSeconds());
        if (metadata != null) {
            event.putAll(metadata);
        }

        events.computeIfAbsent(userId, k -> new CopyOnWriteArrayList<>()).add(event);
        List<Map<String, Object>> userEvents = events.get(userId);
        if (userEvents.size() > 1000) {
            userEvents.remove(0);
        }

        Map<String, Object> profile = getOrCreateProfile(userId);
        synchronized (profile) {
            updateProfile(profile, event);
        }
        return event;
    }

    public void recordImpression(
            String userId,
            List<Product> products,
            String requestId,
            String scene,
            String experimentGroup
    ) {
        if (products == null || products.isEmpty()) {
            return;
        }
        for (Product product : products) {
            Map<String, Object> metadata = new HashMap<>();
            metadata.put("name", product.getName());
            metadata.put("category", product.getCategory());
            metadata.put("price", product.getPrice());
            metadata.put("request_id", requestId);
            metadata.put("scene", scene);
            metadata.put("experiment_group", experimentGroup);
            recordBehavior(userId, "impression", product.getProductId(), metadata);
        }

        Map<String, Object> profile = getOrCreateProfile(userId);
        synchronized (profile) {
            Map<String, Object> lastRecommendation = new HashMap<>();
            lastRecommendation.put("request_id", requestId);
            lastRecommendation.put("scene", scene);
            lastRecommendation.put("experiment_group", experimentGroup);
            lastRecommendation.put("product_ids", products.stream().map(Product::getProductId).collect(Collectors.toList()));
            lastRecommendation.put("ts", nowSeconds());
            profile.put("last_recommendation", lastRecommendation);
            profile.put("updated_at", nowSeconds());
        }
    }

    public Map<String, Object> getUserMemory(String userId) {
        List<Map<String, Object>> userEvents = events.getOrDefault(userId, List.of());
        Map<String, Object> result = new HashMap<>();
        result.put("user_id", userId);
        result.put("view_count_1h", count(userEvents, "view", 3600));
        result.put("view_count_24h", count(userEvents, "view", 86400));
        result.put("click_count_1h", count(userEvents, "click", 3600));
        result.put("purchase_count_7d", count(userEvents, "purchase", 604800));
        result.put("impression_count_24h", count(userEvents, "impression", 86400));
        result.put("recent_views", recentItems(userEvents, "view", 86400, 20));
        result.put("recent_purchases", recentItems(userEvents, "purchase", 604800, 10));
        result.put("recent_impressions", recentItems(userEvents, "impression", 86400, 20));
        result.put("profile_snapshot", getProfileSnapshot(userId));
        result.put("memory_backend", "memory");
        return result;
    }

    public Map<String, Object> getProfileSnapshot(String userId) {
        Map<String, Object> profile = profiles.get(userId);
        if (profile == null) {
            return emptyProfile(userId);
        }
        synchronized (profile) {
            return new LinkedHashMap<>(profile);
        }
    }

    public void forgetUser(String userId) {
        events.remove(userId);
        profiles.remove(userId);
    }

    private Map<String, Object> getOrCreateProfile(String userId) {
        return profiles.computeIfAbsent(userId, this::emptyProfile);
    }

    private Map<String, Object> emptyProfile(String userId) {
        Map<String, Object> profile = new LinkedHashMap<>();
        profile.put("user_id", userId);
        profile.put("behavior_counts", new HashMap<String, Integer>());
        profile.put("preferred_categories", new ArrayList<String>());
        profile.put("category_affinity", new HashMap<String, Integer>());
        profile.put("last_items", new ArrayList<String>());
        profile.put("purchase_count", 0);
        profile.put("total_spent", 0.0);
        profile.put("created_at", nowSeconds());
        profile.put("updated_at", nowSeconds());
        return profile;
    }

    @SuppressWarnings("unchecked")
    private void updateProfile(Map<String, Object> profile, Map<String, Object> event) {
        String behaviorType = String.valueOf(event.getOrDefault("behavior_type", "event"));
        Map<String, Integer> counts = (Map<String, Integer>) profile.get("behavior_counts");
        counts.put(behaviorType, counts.getOrDefault(behaviorType, 0) + 1);

        Object category = event.get("category");
        if (category != null) {
            Map<String, Integer> affinity = (Map<String, Integer>) profile.get("category_affinity");
            String categoryName = String.valueOf(category);
            affinity.put(categoryName, affinity.getOrDefault(categoryName, 0) + 1);
            List<String> preferred = affinity.entrySet().stream()
                    .sorted(Map.Entry.<String, Integer>comparingByValue(Comparator.reverseOrder()))
                    .limit(5)
                    .map(Map.Entry::getKey)
                    .collect(Collectors.toList());
            profile.put("preferred_categories", preferred);
        }

        Object itemId = event.get("item_id");
        if (itemId != null) {
            List<String> lastItems = (List<String>) profile.get("last_items");
            lastItems.add(String.valueOf(itemId));
            if (lastItems.size() > 20) {
                lastItems.remove(0);
            }
        }

        if ("purchase".equals(behaviorType)) {
            double amount = toDouble(event.getOrDefault("amount", event.getOrDefault("price", 0)));
            profile.put("purchase_count", ((Number) profile.getOrDefault("purchase_count", 0)).intValue() + 1);
            profile.put("total_spent", toDouble(profile.getOrDefault("total_spent", 0.0)) + amount);
        }

        profile.put("last_behavior_at", event.get("ts"));
        profile.put("updated_at", nowSeconds());
    }

    private long count(List<Map<String, Object>> events, String type, long windowSeconds) {
        double cutoff = nowSeconds() - windowSeconds;
        return events.stream()
                .filter(e -> type.equals(e.get("behavior_type")))
                .filter(e -> toDouble(e.get("ts")) >= cutoff)
                .count();
    }

    private List<String> recentItems(List<Map<String, Object>> events, String type, long windowSeconds, int limit) {
        double cutoff = nowSeconds() - windowSeconds;
        List<String> items = events.stream()
                .filter(e -> type.equals(e.get("behavior_type")))
                .filter(e -> toDouble(e.get("ts")) >= cutoff)
                .map(e -> String.valueOf(e.get("item_id")))
                .collect(Collectors.toList());
        if (items.size() <= limit) {
            return items;
        }
        return items.subList(items.size() - limit, items.size());
    }

    private double nowSeconds() {
        return System.currentTimeMillis() / 1000.0;
    }

    private double toDouble(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception e) {
            return 0.0;
        }
    }
}
