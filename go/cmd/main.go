package main

import (
	"log"
	"os"

	"github.com/bcefghj/multi-agent-ecommerce/handler"
	"github.com/bcefghj/multi-agent-ecommerce/orchestrator"
	"github.com/gin-gonic/gin"
)

func main() {
	apiKey := envOrDefault("ECOM_LLM_API_KEY", "your_api_key_here")
	baseURL := envOrDefault("ECOM_LLM_BASE_URL", "https://api.minimax.chat/v1")
	modelName := envOrDefault("ECOM_LLM_MODEL", "MiniMax-M1")

	supervisor := orchestrator.NewSupervisor(apiKey, baseURL, modelName)
	h := handler.NewHandler(supervisor)

	r := gin.Default()
	h.RegisterRoutes(r)

	port := envOrDefault("PORT", "8080")
	log.Printf("Starting Go multi-agent server on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatal(err)
	}
}

func envOrDefault(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}
