# 🌌 Astra Intelligence v7.5 – System Map

**Build:** Stable v7.5
**Date:** 2025-12-15 12:16:40
**Status:** ✅ All modules validated and linked

## 🧭 High-Level Architecture

Guardian → Engine → Agents → Forecast
     ↓           ↓         ↓
   Utils       State     Learning
     ↓           ↓         ↓
   Fetch → UI / Dashboard → Users

## 🧩 Module Overview

| Module | Role | Key Dependencies |
|---------|------|------------------|
| **Guardian** | Core safety, diagnostics, schema validation | Engine, Utils |
| **Engine** | Orchestrator and logic coordinator | Agents, State |
| **Agents** | Decision modules (momentum, neural, etc.) | Utils, Forecast |
| **Forecast** | Predictive and model inference | Learning, State |
| **Learning** | Replay buffer and adaptive training | Forecast, State |
| **State** | Data pipeline and tensor builders | Utils, Fetch |
| **Fetch** | Data acquisition and preprocessing | Utils, Guardian |
| **Utils** | Shared wrappers and safe operations | Guardian |
| **UI** | Dashboard and analytics | Engine, Forecast |
| **Chart_Core** | Visualization and chart rendering | UI, Utils |

✅ System validated and archived successfully.
