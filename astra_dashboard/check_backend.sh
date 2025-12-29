#!/bin/bash
echo "🔍 Checking Astra Backend..."
curl -s http://127.0.0.1:8001/openapi.json | jq '.paths | keys'
echo " "
echo "📊 Learning Metrics:"
curl -s http://127.0.0.1:8001/learning/metrics | jq
