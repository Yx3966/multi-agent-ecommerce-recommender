package agent

import (
	"fmt"
	"log"
	"sync/atomic"
	"time"

	"github.com/bcefghj/multi-agent-ecommerce/model"
)

// Agent is the interface all domain agents implement.
type Agent interface {
	Name() string
	Run(params map[string]any) model.AgentResult
}

// BaseAgent provides retry, timing, and fallback logic.
type BaseAgent struct {
	AgentName  string
	Timeout    time.Duration
	MaxRetries int

	callCount  int64
	errorCount int64
}

// ExecuteFunc is the core logic a concrete agent supplies.
type ExecuteFunc func(params map[string]any) (model.AgentResult, error)

func (b *BaseAgent) Name() string { return b.AgentName }

// RunWithRetry wraps execute with timing, retries, and fallback.
func (b *BaseAgent) RunWithRetry(params map[string]any, fn ExecuteFunc) model.AgentResult {
	atomic.AddInt64(&b.callCount, 1)
	start := time.Now()

	var lastErr error
	for attempt := 0; attempt < b.MaxRetries; attempt++ {
		result, err := fn(params)
		if err == nil {
			result.LatencyMs = float64(time.Since(start).Milliseconds())
			log.Printf("[%s] success in %.1fms", b.AgentName, result.LatencyMs)
			return result
		}
		lastErr = err
		log.Printf("[%s] attempt %d failed: %v", b.AgentName, attempt+1, err)
		if attempt < b.MaxRetries-1 {
			time.Sleep(time.Duration(500*(1<<attempt)) * time.Millisecond)
		}
	}

	atomic.AddInt64(&b.errorCount, 1)
	latency := float64(time.Since(start).Milliseconds())
	errMsg := ""
	if lastErr != nil {
		errMsg = lastErr.Error()
	}
	return model.AgentResult{
		AgentName:  b.AgentName,
		Success:    false,
		LatencyMs:  latency,
		Error:      errMsg,
		Confidence: 0.0,
	}
}

func (b *BaseAgent) ErrorRate() float64 {
	calls := atomic.LoadInt64(&b.callCount)
	if calls == 0 {
		return 0
	}
	return float64(atomic.LoadInt64(&b.errorCount)) / float64(calls)
}

func errResult(name string, err error) model.AgentResult {
	return model.AgentResult{
		AgentName: name,
		Success:   false,
		Error:     fmt.Sprintf("%v", err),
	}
}
