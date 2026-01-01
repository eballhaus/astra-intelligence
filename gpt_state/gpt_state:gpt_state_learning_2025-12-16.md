# Astra Intelligence — GPT State File
# Session Topic: Astra Learning System Reactivation
# Timestamp: 2025-12-16 15:08 EST

Current Goal: Re-enable Astra’s full learning subsystem (found under archive/astra_modules_legacy_archived_20251215/learning) so the platform can train, adapt, and improve predictive accuracy in the background—without slowing or breaking the dashboard.

1️⃣ FILES AND LOCATIONS
archive/astra_modules_legacy_archived_20251215/learning/
├── continual_trainer.py
├── fusion_calibrator.py
├── fusion_weight_optimizer.py
├── guardian_fusion_optimizer.py
├── learning_engine.py
├── learning_store.py
├── meta_memory.py
├── paper_trader.py
├── performance_tracker.py
├── performance_tracker.json
├── replay_buffer.py
├── scheduler.py
└── __init__.py
Destination: /Users/ericballhaus/Desktop/astra-intelligence/learning/

This package supplies Astra’s Learning Core:
• continual training loop (async + scheduled)
• fusion optimization of agent outputs
• replay buffer management
• Guardian-integrated safety checks
• performance tracking and metrics persistence

2️⃣ INTEGRATION PLAN
1. Backup existing folder:
   mv learning learning_EMPTY_$(date +%Y%m%d_%H%M)
2. Copy archived learning modules:
   cp -R archive/astra_modules_legacy_archived_20251215/learning ./learning
3. Verify imports using Python block:
   learning.learning_engine, learning.replay_buffer, learning.continual_trainer, learning.performance_tracker
4. Background Learning Activation:
   Create engine/learning_manager.py with async loop:
   import asyncio
   from learning.learning_engine import start_learning_cycle
   async def background_learning():
       while True:
           try:
               await start_learning_cycle()
           except Exception as e:
               print("Learning cycle error:", e)
           await asyncio.sleep(3600)
   Call asyncio.create_task(background_learning()) during dashboard startup.
5. Guardian Integration:
   Every learning cycle logs through GuardianV7, keeping errors isolated from Streamlit.

3️⃣ LEARNING MONITOR TAB DESIGN
New file: ui/dashboard/tab_learning_monitor.py
Purpose: display what Astra has learned and how well it’s performing.
Metrics to show (live from /tmp/astra_cache/performance_tracker.json or learning store):

Metric | Description
-------|-------------
Accuracy % | ratio of correct to total predictions
Confidence % | average model confidence per cycle
Total Trades | simulated trades via paper_trader
Profit/Loss ($) | cumulative performance from paper trades
Correct / Wrong | integer count of decisions
Learning Cycles | number of retrain iterations
Last Update | timestamp of most recent cycle

Example snippet:
import streamlit as st, json, os
def render_learning_monitor():
    st.title("🧠 Astra Learning Monitor")
    path = "/tmp/astra_cache/performance_tracker.json"
    if not os.path.exists(path):
        st.info("No learning metrics yet.")
        return
    data = json.load(open(path))
    st.metric("Accuracy", f"{data['accuracy']:.2f}%")
    st.metric("Confidence", f"{data['confidence']:.2f}%")
    st.metric("Trades", data['trades'])
    st.metric("Profit", f"${data['profit']:.2f}")
    st.metric("Correct / Wrong", f"{data['correct']} / {data['wrong']}")

4️⃣ PERFORMANCE AND SAFETY
• Runs asynchronously; main dashboard thread remains responsive.
• CPU usage limited by scheduled intervals and sleep timers.
• GuardianV7 monitors every cycle and logs anomalies.
• Caches large objects to /tmp/astra_cache/ to avoid RAM bloat.

5️⃣ EXPECTED BEHAVIOR AFTER ACTIVATION
✅ Dashboard runs normally.
✅ Background task starts learning quietly and logs via Guardian.
✅ performance_tracker.json populates with real learning metrics.
✅ Learning Monitor tab displays accuracy, confidence, trades, and profit trends.

6️⃣ FUTURE UPGRADES AND ENHANCEMENTS
Priority | Feature | Description
---------|----------|-------------
🔹 | Dynamic Learning Rate Control | adjust based on Guardian feedback
🔹 | GPU Acceleration Toggle | optional TensorFlow/PyTorch training support
🔹 | Learning History Graph | visualize accuracy/confidence over time
🔹 | Model Version Tracker | show weights version and best epoch
🔹 | Reinforcement Policy Improvement | extend paper trader to real time RL simulation
🔹 | API Telemetry Sync | periodically push learning metrics to Astra Cloud API
🔹 | Guardian Intervention UI | live toggle to pause/resume learning if Guardian detects risk

7️⃣ NEXT ACTION CHECKLIST
1. Run backup and copy commands to restore learning modules.
2. Confirm imports pass using the provided Python test block.
3. Add background_learning() to dashboard startup.
4. Create and register tab_learning_monitor.py.
5. Commit and push changes to GitHub (main or astra-v9 branch).

8️⃣ RESUME FROM THIS STATE
When the next session begins, read this file to restore context and continue with activating the learning manager and integrating the Learning Monitor tab into Streamlit navigation.

Session Status: Astra Learning Framework ready for activation.
Next Stage: Create engine/learning_manager.py and ui/dashboard/tab_learning_monitor.py, verify safe background training.
Timestamp Recorded: 2025-12-16 15:08 EST
