package handler

import (
	"net/http"

	"github.com/bcefghj/multi-agent-ecommerce/model"
	"github.com/bcefghj/multi-agent-ecommerce/orchestrator"
	"github.com/gin-gonic/gin"
)

type Handler struct {
	supervisor *orchestrator.Supervisor
}

func NewHandler(supervisor *orchestrator.Supervisor) *Handler {
	return &Handler{supervisor: supervisor}
}

func (h *Handler) RegisterRoutes(r *gin.Engine) {
	r.GET("/health", h.Health)
	v1 := r.Group("/api/v1")
	{
		v1.POST("/recommend", h.Recommend)
		v1.GET("/experiments", h.Experiments)
	}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "healthy", "language": "go"})
}

func (h *Handler) Recommend(c *gin.Context) {
	var req model.RecommendationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	resp := h.supervisor.Recommend(req)
	c.JSON(http.StatusOK, resp)
}

func (h *Handler) Experiments(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"rec_strategy": gin.H{
			"name":   "推荐策略实验",
			"groups": gin.H{"control": "rule_based", "treatment_llm": "llm_rerank"},
		},
	})
}
