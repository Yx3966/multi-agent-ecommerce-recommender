package agent

import (
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/model"
)

const (
	safetyStockThreshold = 50
	lowStockThreshold    = 100
	hotItemPurchaseLimit = 2
)

// InventoryAgent — 实时库存查询 + 库存预警 + 限购策略
type InventoryAgent struct {
	BaseAgent
}

func NewInventoryAgent() *InventoryAgent {
	return &InventoryAgent{
		BaseAgent: BaseAgent{AgentName: "inventory", Timeout: 5 * time.Second, MaxRetries: 2},
	}
}

func (a *InventoryAgent) Run(params map[string]any) model.AgentResult {
	return a.RunWithRetry(params, a.execute)
}

func (a *InventoryAgent) execute(params map[string]any) (model.AgentResult, error) {
	products, _ := params["products"].([]model.Product)

	var available []string
	var alerts []map[string]any
	purchaseLimits := make(map[string]int)

	for _, p := range products {
		if p.Stock <= 0 {
			continue
		}
		available = append(available, p.ProductID)

		if p.Stock <= safetyStockThreshold {
			alerts = append(alerts, map[string]any{
				"product_id":    p.ProductID,
				"name":          p.Name,
				"current_stock": p.Stock,
				"level":         "critical",
				"action":        "urgent_restock",
			})
		} else if p.Stock <= lowStockThreshold {
			alerts = append(alerts, map[string]any{
				"product_id":    p.ProductID,
				"name":          p.Name,
				"current_stock": p.Stock,
				"level":         "warning",
				"action":        "plan_restock",
			})
		}

		if limit := calcPurchaseLimit(p); limit > 0 {
			purchaseLimits[p.ProductID] = limit
		}
	}

	return model.AgentResult{
		AgentName: a.AgentName,
		Success:   true,
		Data: map[string]any{
			"available_products": available,
			"low_stock_alerts":   alerts,
			"purchase_limits":    purchaseLimits,
			"total_checked":      len(products),
			"available_count":    len(available),
		},
		Confidence: 0.95,
	}, nil
}

func calcPurchaseLimit(p model.Product) int {
	isHot := containsAny(p.Tags, "新品", "旗舰")
	if p.Stock <= safetyStockThreshold {
		return 1
	}
	if p.Stock <= lowStockThreshold && isHot {
		return hotItemPurchaseLimit
	}
	if isHot && p.Stock <= 300 {
		return 3
	}
	return 0
}

func containsAny(tags []string, targets ...string) bool {
	for _, t := range tags {
		for _, target := range targets {
			if t == target {
				return true
			}
		}
	}
	return false
}
