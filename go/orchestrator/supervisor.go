package orchestrator

import (
	"log"
	"sync"
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/agent"
	"github.com/bcefghj/multi-agent-ecommerce/model"
	"github.com/bcefghj/multi-agent-ecommerce/service"
	"github.com/google/uuid"
)

// Supervisor coordinates four agents with goroutine-based parallelism and channel aggregation.
//
//	        ┌──────────────┐
//	        │  Supervisor   │
//	        └──────┬───────┘
//	   ┌─────┬─────┼─────┬──────┐
//	   ▼     ▼     ▼     ▼      │    (goroutines)
//	Profile Rec  Copy Inventory │
//	   └─────┴─────┴─────┘      │    (sync.WaitGroup)
//	          ▼                  │
//	      Aggregator ◄───────────┘
type Supervisor struct {
	profileAgent  *agent.UserProfileAgent
	recAgent      *agent.ProductRecAgent
	copyAgent     *agent.MarketingCopyAgent
	inventoryAgent *agent.InventoryAgent
	abTest        *service.ABTestEngine
}

func NewSupervisor(apiKey, baseURL, modelName string) *Supervisor {
	return &Supervisor{
		profileAgent:   agent.NewUserProfileAgent(apiKey, baseURL, modelName),
		recAgent:       agent.NewProductRecAgent(apiKey, baseURL, modelName),
		copyAgent:      agent.NewMarketingCopyAgent(apiKey, baseURL, modelName),
		inventoryAgent: agent.NewInventoryAgent(),
		abTest:         service.NewABTestEngine(),
	}
}

func (s *Supervisor) Recommend(req model.RecommendationRequest) model.RecommendationResponse {
	requestID := uuid.New().String()
	start := time.Now()
	agentResults := make(map[string]model.AgentResult)
	var mu sync.Mutex

	if req.NumItems == 0 {
		req.NumItems = 10
	}

	expGroup := s.abTest.Assign(req.UserID)
	log.Printf("[Supervisor] start request=%s user=%s", requestID, req.UserID)

	// Phase 1: parallel — user profile + product recall
	var profileResult, recResult model.AgentResult
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		profileResult = s.profileAgent.Run(map[string]any{"user_id": req.UserID})
		mu.Lock()
		agentResults["user_profile"] = profileResult
		mu.Unlock()
	}()

	go func() {
		defer wg.Done()
		recResult = s.recAgent.Run(map[string]any{"num_items": req.NumItems * 2})
		mu.Lock()
		agentResults["product_recall"] = recResult
		mu.Unlock()
	}()

	wg.Wait()

	var profile *model.UserProfile
	if p, ok := profileResult.Data["profile"].(model.UserProfile); ok {
		profile = &p
	}
	var rawProducts []model.Product
	if ps, ok := recResult.Data["products"].([]model.Product); ok {
		rawProducts = ps
	}

	// Phase 2: parallel — rerank + inventory
	var rerankResult, invResult model.AgentResult
	wg.Add(2)

	go func() {
		defer wg.Done()
		rerankResult = s.recAgent.Run(map[string]any{
			"user_profile": profile,
			"num_items":    req.NumItems,
		})
		mu.Lock()
		agentResults["rerank"] = rerankResult
		mu.Unlock()
	}()

	go func() {
		defer wg.Done()
		invResult = s.inventoryAgent.Run(map[string]any{"products": rawProducts})
		mu.Lock()
		agentResults["inventory"] = invResult
		mu.Unlock()
	}()

	wg.Wait()

	var rankedProducts []model.Product
	if ps, ok := rerankResult.Data["products"].([]model.Product); ok {
		rankedProducts = ps
	} else {
		rankedProducts = rawProducts
	}

	availSet := make(map[string]bool)
	if avail, ok := invResult.Data["available_products"].([]string); ok {
		for _, id := range avail {
			availSet[id] = true
		}
	}

	var finalProducts []model.Product
	for _, p := range rankedProducts {
		if availSet[p.ProductID] {
			finalProducts = append(finalProducts, p)
		}
		if len(finalProducts) >= req.NumItems {
			break
		}
	}
	if len(finalProducts) == 0 && len(rankedProducts) > 0 {
		limit := req.NumItems
		if limit > len(rankedProducts) {
			limit = len(rankedProducts)
		}
		finalProducts = rankedProducts[:limit]
	}

	// Phase 3: marketing copy
	copyResult := s.copyAgent.Run(map[string]any{
		"user_profile": profile,
		"products":     finalProducts,
	})
	mu.Lock()
	agentResults["marketing_copy"] = copyResult
	mu.Unlock()

	var copies []map[string]string
	if c, ok := copyResult.Data["copies"].([]map[string]string); ok {
		copies = c
	}

	totalLatency := float64(time.Since(start).Milliseconds())
	log.Printf("[Supervisor] complete request=%s latency=%.1fms products=%d", requestID, totalLatency, len(finalProducts))

	return model.RecommendationResponse{
		RequestID:       requestID,
		UserID:          req.UserID,
		Products:        finalProducts,
		MarketingCopies: copies,
		ExperimentGroup: expGroup,
		AgentResults:    agentResults,
		TotalLatencyMs:  totalLatency,
		Timestamp:       time.Now(),
	}
}
