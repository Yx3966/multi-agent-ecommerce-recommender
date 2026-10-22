package com.ecommerce.agent;

import com.ecommerce.model.AgentResult;
import com.ecommerce.model.Product;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * 库存决策Agent — 实时库存查询 + 库存预警 + 限购策略
 */
@Component
public class InventoryAgent extends BaseAgent {

    private static final int SAFETY_STOCK_THRESHOLD = 50;
    private static final int LOW_STOCK_THRESHOLD = 100;
    private static final int HOT_ITEM_PURCHASE_LIMIT = 2;

    public InventoryAgent() {
        super("inventory", 5.0, 2);
    }

    @Override
    @SuppressWarnings("unchecked")
    protected AgentResult execute(Map<String, Object> params) throws Exception {
        List<Product> products = (List<Product>) params.getOrDefault("products", List.of());

        List<String> available = new ArrayList<>();
        List<Map<String, Object>> alerts = new ArrayList<>();
        Map<String, Integer> purchaseLimits = new HashMap<>();

        for (Product product : products) {
            int stock = checkStock(product);
            if (stock <= 0) continue;

            available.add(product.getProductId());

            if (stock <= SAFETY_STOCK_THRESHOLD) {
                alerts.add(Map.of(
                        "product_id", product.getProductId(),
                        "name", product.getName(),
                        "current_stock", stock,
                        "level", "critical",
                        "action", "urgent_restock"
                ));
            } else if (stock <= LOW_STOCK_THRESHOLD) {
                alerts.add(Map.of(
                        "product_id", product.getProductId(),
                        "name", product.getName(),
                        "current_stock", stock,
                        "level", "warning",
                        "action", "plan_restock"
                ));
            }

            Integer limit = calcPurchaseLimit(product, stock);
            if (limit != null) {
                purchaseLimits.put(product.getProductId(), limit);
            }
        }

        Map<String, Object> data = new HashMap<>();
        data.put("available_products", available);
        data.put("low_stock_alerts", alerts);
        data.put("purchase_limits", purchaseLimits);
        data.put("total_checked", products.size());
        data.put("available_count", available.size());

        return AgentResult.builder()
                .agentName(name)
                .success(true)
                .data(data)
                .confidence(0.95)
                .build();
    }

    private int checkStock(Product product) {
        return product.getStock();
    }

    private Integer calcPurchaseLimit(Product product, int stock) {
        boolean isHot = product.getTags() != null &&
                (product.getTags().contains("新品") || product.getTags().contains("旗舰"));
        if (stock <= SAFETY_STOCK_THRESHOLD) return 1;
        if (stock <= LOW_STOCK_THRESHOLD && isHot) return HOT_ITEM_PURCHASE_LIMIT;
        if (isHot && stock <= 300) return 3;
        return null;
    }
}
