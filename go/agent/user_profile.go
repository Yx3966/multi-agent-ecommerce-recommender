package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/model"
	openai "github.com/sashabaranov/go-openai"
)

// UserProfileAgent — 用户画像分析：实时特征 + RFM模型 + 用户分群
type UserProfileAgent struct {
	BaseAgent
	client *openai.Client
	model  string
}

func NewUserProfileAgent(apiKey, baseURL, modelName string) *UserProfileAgent {
	cfg := openai.DefaultConfig(apiKey)
	cfg.BaseURL = baseURL
	return &UserProfileAgent{
		BaseAgent: BaseAgent{AgentName: "user_profile", Timeout: 5 * time.Second, MaxRetries: 2},
		client:    openai.NewClientWithConfig(cfg),
		model:     modelName,
	}
}

func (a *UserProfileAgent) Run(params map[string]any) model.AgentResult {
	return a.RunWithRetry(params, a.execute)
}

func (a *UserProfileAgent) execute(params map[string]any) (model.AgentResult, error) {
	userID, _ := params["user_id"].(string)
	behavior := map[string]any{
		"user_id":            userID,
		"recent_views":       []string{"手机", "耳机", "平板"},
		"recent_purchases":   []string{"充电器"},
		"view_count_7d":      25,
		"purchase_count_30d": 3,
		"avg_order_amount":   299.0,
	}
	behaviorJSON, _ := json.Marshal(behavior)

	systemPrompt := `你是电商用户画像分析专家。输出JSON:
{"segments":["active"],"preferred_categories":["手机"],"price_range":[0,10000],
 "rfm_score":{"recency":0.8,"frequency":0.5,"monetary":0.6},
 "real_time_tags":{"活跃时段":"晚间"}}
只输出JSON。`

	resp, err := a.client.CreateChatCompletion(context.Background(), openai.ChatCompletionRequest{
		Model: a.model,
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleSystem, Content: systemPrompt},
			{Role: openai.ChatMessageRoleUser, Content: fmt.Sprintf("用户ID: %s\n行为数据: %s", userID, behaviorJSON)},
		},
		Temperature: 0.3,
		MaxTokens:   1024,
	})
	if err != nil {
		return model.AgentResult{}, err
	}

	content := resp.Choices[0].Message.Content
	profile := parseProfile(userID, content)

	return model.AgentResult{
		AgentName:  a.AgentName,
		Success:    true,
		Data:       map[string]any{"profile": profile, "raw": content},
		Confidence: 0.85,
	}, nil
}

func parseProfile(userID, raw string) model.UserProfile {
	profile := model.UserProfile{
		UserID:   userID,
		Segments: []string{"active"},
	}
	var data map[string]any
	if err := json.Unmarshal([]byte(raw), &data); err != nil {
		return profile
	}
	if segs, ok := data["segments"].([]any); ok {
		profile.Segments = make([]string, len(segs))
		for i, s := range segs {
			profile.Segments[i], _ = s.(string)
		}
	}
	if cats, ok := data["preferred_categories"].([]any); ok {
		profile.PreferredCategories = make([]string, len(cats))
		for i, c := range cats {
			profile.PreferredCategories[i], _ = c.(string)
		}
	}
	return profile
}
