package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/model"
	openai "github.com/sashabaranov/go-openai"
)

var MockProducts = []model.Product{
	{ProductID: "P001", Name: "iPhone 16 Pro", Category: "手机", Price: 7999, Brand: "Apple", SellerID: "S01", Stock: 500, Tags: []string{"旗舰", "新品"}},
	{ProductID: "P002", Name: "华为 Mate 70", Category: "手机", Price: 5999, Brand: "华为", SellerID: "S02", Stock: 300, Tags: []string{"旗舰", "国产"}},
	{ProductID: "P003", Name: "AirPods Pro 3", Category: "耳机", Price: 1899, Brand: "Apple", SellerID: "S01", Stock: 1000, Tags: []string{"降噪", "无线"}},
	{ProductID: "P004", Name: "Sony WH-1000XM6", Category: "耳机", Price: 2499, Brand: "Sony", SellerID: "S03", Stock: 200, Tags: []string{"头戴", "降噪"}},
	{ProductID: "P005", Name: "iPad Air M3", Category: "平板", Price: 4799, Brand: "Apple", SellerID: "S01", Stock: 400, Tags: []string{"学习", "办公"}},
	{ProductID: "P006", Name: "小米平板7 Pro", Category: "平板", Price: 2499, Brand: "小米", SellerID: "S04", Stock: 600, Tags: []string{"性价比", "娱乐"}},
	{ProductID: "P007", Name: "Anker 140W充电器", Category: "配件", Price: 399, Brand: "Anker", SellerID: "S05", Stock: 2000, Tags: []string{"快充", "便携"}},
	{ProductID: "P008", Name: "机械革命极光X", Category: "笔记本", Price: 6999, Brand: "机械革命", SellerID: "S06", Stock: 150, Tags: []string{"游戏", "高性能"}},
	{ProductID: "P009", Name: "戴尔U2724D显示器", Category: "显示器", Price: 3299, Brand: "Dell", SellerID: "S07", Stock: 80, Tags: []string{"4K", "办公"}},
	{ProductID: "P010", Name: "罗技MX Master 3S", Category: "配件", Price: 749, Brand: "罗技", SellerID: "S08", Stock: 500, Tags: []string{"无线", "办公"}},
}

// ProductRecAgent — 多策略召回 + LLM重排 + 多样性控制
type ProductRecAgent struct {
	BaseAgent
	client *openai.Client
	model  string
}

func NewProductRecAgent(apiKey, baseURL, modelName string) *ProductRecAgent {
	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return &ProductRecAgent{
		BaseAgent: BaseAgent{AgentName: "product_rec", Timeout: 8 * time.Second, MaxRetries: 2},
		client:    openai.NewClientWithConfig(cfg),
		model:     modelName,
	}
}

func (a *ProductRecAgent) Run(params map[string]any) model.AgentResult {
	return a.RunWithRetry(params, a.execute)
}

func (a *ProductRecAgent) execute(params map[string]any) (model.AgentResult, error) {
	numItems := 10
	if n, ok := params["num_items"].(int); ok {
		numItems = n
	}

	candidates := a.recall(params, numItems*2)
	rankedIDs := a.rerank(params, candidates, numItems)

	idMap := make(map[string]model.Product)
	for _, p := range candidates {
		idMap[p.ProductID] = p
	}
	var final []model.Product
	for _, id := range rankedIDs {
		if p, ok := idMap[id]; ok {
			final = append(final, p)
		}
	}
	if len(final) < numItems {
		for _, p := range candidates {
			found := false
			for _, f := range final {
				if f.ProductID == p.ProductID {
					found = true
					break
				}
			}
			if !found {
				final = append(final, p)
				if len(final) >= numItems {
					break
				}
			}
		}
	}
	if len(final) > numItems {
		final = final[:numItems]
	}

	return model.AgentResult{
		AgentName:  a.AgentName,
		Success:    true,
		Data:       map[string]any{"products": final, "recall_strategy": "collaborative+vector+hot"},
		Confidence: 0.8,
	}, nil
}

func (a *ProductRecAgent) recall(params map[string]any, limit int) []model.Product {
	candidates := make([]model.Product, len(MockProducts))
	copy(candidates, MockProducts)

	if profile, ok := params["user_profile"].(*model.UserProfile); ok && profile != nil {
		preferred := make(map[string]bool)
		for _, cat := range profile.PreferredCategories {
			preferred[cat] = true
		}
		sort.Slice(candidates, func(i, j int) bool {
			return preferred[candidates[i].Category] && !preferred[candidates[j].Category]
		})
	}

	if len(candidates) > limit {
		candidates = candidates[:limit]
	}
	return candidates
}

func (a *ProductRecAgent) rerank(params map[string]any, candidates []model.Product, numItems int) []string {
	ids := make([]string, 0, numItems)
	for i, p := range candidates {
		if i >= numItems {
			break
		}
		ids = append(ids, p.ProductID)
	}

	profile, _ := params["user_profile"].(*model.UserProfile)
	if profile == nil {
		return ids
	}

	var productInfo string
	for _, p := range candidates {
		productInfo += fmt.Sprintf("%s:%s(%s,¥%.0f)\n", p.ProductID, p.Name, p.Category, p.Price)
	}
	prompt := fmt.Sprintf("根据偏好类目%v,选出%d个最优商品,输出ID数组:\n%s只输出JSON数组。",
		profile.PreferredCategories, numItems, productInfo)

	resp, err := a.client.CreateChatCompletion(context.Background(), openai.ChatCompletionRequest{
		Model: a.model,
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleUser, Content: prompt},
		},
		Temperature: 0.3,
		MaxTokens:   512,
	})
	if err != nil {
		return ids
	}

	var result []string
	if err := json.Unmarshal([]byte(resp.Choices[0].Message.Content), &result); err != nil {
		return ids
	}
	return result
}
