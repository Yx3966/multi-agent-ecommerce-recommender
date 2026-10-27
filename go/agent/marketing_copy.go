package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/model"
	openai "github.com/sashabaranov/go-openai"
)

var promptTemplates = map[string]string{
	"new_user":        "为新用户撰写欢迎文案,热情友好,突出新人优惠。",
	"high_value":      "为VIP用户撰写文案,品质尊享,突出品牌价值。",
	"price_sensitive": "为价格敏感用户撰写文案,突出性价比和优惠。",
	"active":          "为活跃用户撰写文案,突出商品亮点和场景。",
	"churn_risk":      "为流失风险用户撰写召回文案,突出专属折扣。",
}

var forbiddenWords = []string{"最好", "第一", "国家级", "全球首", "绝对", "100%", "永久", "万能"}

// MarketingCopyAgent — Prompt模板引擎 + 个性化生成 + 广告法合规
type MarketingCopyAgent struct {
	BaseAgent
	client *openai.Client
	model  string
}

func NewMarketingCopyAgent(apiKey, baseURL, modelName string) *MarketingCopyAgent {
	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return &MarketingCopyAgent{
		BaseAgent: BaseAgent{AgentName: "marketing_copy", Timeout: 10 * time.Second, MaxRetries: 2},
		client:    openai.NewClientWithConfig(cfg),
		model:     modelName,
	}
}

func (a *MarketingCopyAgent) Run(params map[string]any) model.AgentResult {
	return a.RunWithRetry(params, a.execute)
}

func (a *MarketingCopyAgent) execute(params map[string]any) (model.AgentResult, error) {
	products, _ := params["products"].([]model.Product)
	if len(products) == 0 {
		return model.AgentResult{
			AgentName: a.AgentName, Success: true,
			Data: map[string]any{"copies": []map[string]string{}}, Confidence: 1.0,
		}, nil
	}

	profile, _ := params["user_profile"].(*model.UserProfile)
	templateKey := selectTemplate(profile)
	systemPrompt := promptTemplates[templateKey] +
		"\n每个商品生成一条文案(30-50字)。输出JSON数组: [{\"product_id\":\"xxx\",\"copy\":\"文案\"}]"

	var productInfo string
	for _, p := range products {
		productInfo += fmt.Sprintf("ID:%s %s ¥%.0f %v\n", p.ProductID, p.Name, p.Price, p.Tags)
	}

	resp, err := a.client.CreateChatCompletion(context.Background(), openai.ChatCompletionRequest{
		Model: a.model,
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleSystem, Content: systemPrompt},
			{Role: openai.ChatMessageRoleUser, Content: "商品列表:\n" + productInfo},
		},
		Temperature: 0.9,
		MaxTokens:   2048,
	})
	if err != nil {
		return model.AgentResult{}, err
	}

	copies := parseCopies(resp.Choices[0].Message.Content)
	for i := range copies {
		copies[i] = complianceCheck(copies[i])
	}

	return model.AgentResult{
		AgentName:  a.AgentName,
		Success:    true,
		Data:       map[string]any{"copies": copies, "template_used": templateKey},
		Confidence: 0.9,
	}, nil
}

func selectTemplate(profile *model.UserProfile) string {
	if profile == nil || len(profile.Segments) == 0 {
		return "active"
	}
	priority := []string{"new_user", "high_value", "churn_risk", "price_sensitive", "active"}
	segSet := make(map[string]bool)
	for _, s := range profile.Segments {
		segSet[s] = true
	}
	for _, p := range priority {
		if segSet[p] {
			return p
		}
	}
	return "active"
}

func parseCopies(raw string) []map[string]string {
	cleaned := strings.TrimSpace(raw)
	if strings.HasPrefix(cleaned, "```") {
		if idx := strings.Index(cleaned, "\n"); idx >= 0 {
			cleaned = cleaned[idx+1:]
		}
		if idx := strings.LastIndex(cleaned, "```"); idx >= 0 {
			cleaned = cleaned[:idx]
		}
	}
	var copies []map[string]string
	if err := json.Unmarshal([]byte(cleaned), &copies); err != nil {
		return nil
	}
	return copies
}

func complianceCheck(item map[string]string) map[string]string {
	text := item["copy"]
	for _, word := range forbiddenWords {
		text = strings.ReplaceAll(text, word, "***")
	}
	item["copy"] = text
	return item
}
