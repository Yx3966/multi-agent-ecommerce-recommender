package service

import (
	"crypto/md5"
	"encoding/binary"
	"fmt"
)

const bucketCount = 100

// ABTestEngine — 流量分桶 A/B 测试引擎
type ABTestEngine struct{}

func NewABTestEngine() *ABTestEngine {
	return &ABTestEngine{}
}

func (e *ABTestEngine) Assign(userID string) string {
	bucket := hashBucket(userID, "rec_strategy")
	if bucket < 50 {
		return "control"
	}
	return "treatment_llm"
}

func hashBucket(userID, experimentID string) int {
	raw := fmt.Sprintf("%s:%s", userID, experimentID)
	h := md5.Sum([]byte(raw))
	val := binary.BigEndian.Uint32(h[:4])
	return int(val % bucketCount)
}
