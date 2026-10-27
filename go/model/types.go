package model

import "time"

type UserProfile struct {
	UserID              string            `json:"user_id"`
	Age                 int               `json:"age,omitempty"`
	Gender              string            `json:"gender,omitempty"`
	City                string            `json:"city,omitempty"`
	Segments            []string          `json:"segments"`
	PreferredCategories []string          `json:"preferred_categories"`
	PriceRange          [2]float64        `json:"price_range"`
	RecentViews         []string          `json:"recent_views"`
	RecentPurchases     []string          `json:"recent_purchases"`
	RFMScore            map[string]float64 `json:"rfm_score"`
	RealTimeTags        map[string]any    `json:"real_time_tags"`
}

type Product struct {
	ProductID   string   `json:"product_id"`
	Name        string   `json:"name"`
	Category    string   `json:"category"`
	Price       float64  `json:"price"`
	Description string   `json:"description,omitempty"`
	Brand       string   `json:"brand,omitempty"`
	SellerID    string   `json:"seller_id,omitempty"`
	Stock       int      `json:"stock"`
	Tags        []string `json:"tags"`
	Score       float64  `json:"score,omitempty"`
}

type RecommendationRequest struct {
	UserID   string         `json:"user_id" binding:"required"`
	Scene    string         `json:"scene"`
	NumItems int            `json:"num_items"`
	Context  map[string]any `json:"context"`
}

type RecommendationResponse struct {
	RequestID       string                `json:"request_id"`
	UserID          string                `json:"user_id"`
	Products        []Product             `json:"products"`
	MarketingCopies []map[string]string   `json:"marketing_copies"`
	ExperimentGroup string                `json:"experiment_group"`
	AgentResults    map[string]AgentResult `json:"agent_results"`
	TotalLatencyMs  float64               `json:"total_latency_ms"`
	Timestamp       time.Time             `json:"timestamp"`
}

type AgentResult struct {
	AgentName  string         `json:"agent_name"`
	Success    bool           `json:"success"`
	LatencyMs  float64        `json:"latency_ms"`
	Error      string         `json:"error,omitempty"`
	Data       map[string]any `json:"data,omitempty"`
	Confidence float64        `json:"confidence"`
}
