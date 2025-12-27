import time, traceback
from learning.funnel.astra_funnel import AstraFunnel
from trading.paper_trader import PaperTrader
from learning.replay_buffer import ReplayBuffer
from learning.continual_trainer import ContinualTrainer
from learning.learning_engine import LearningEngine
from learning.fusion_calibrator import FusionCalibrator
from learning.model_manager import ModelManager
from learning.performance_tracker import PerformanceTracker
from learning.learning_log import LearningLog

def run_learning_cycle():
    print("\n[LearningPipeline] 🚀 Starting autonomous learning cycle...")

    funnel = AstraFunnel()
    trader = PaperTrader()
    buffer = ReplayBuffer()
    trainer = ContinualTrainer()
    engine = LearningEngine()
    calibrator = FusionCalibrator()
    models = ModelManager()
    tracker = PerformanceTracker()
    log = LearningLog()

    try:
        # 1️⃣ Fetch latest Astra predictions
        predictions = funnel.run()
        if not predictions:
            print("[LearningPipeline] ⚠️ No predictions — skipping this cycle.")
            return

        # 2️⃣ Feed into simulated PaperTrader
        for p in predictions:
            trader.simulate_trade(p["symbol"], p.get("price"), p.get("target"))

        # 3️⃣ Save outcomes to ReplayBuffer
        buffer.append_batch(trader.get_recent_trades())

        # 4️⃣ Train continuously on new data
        trainer.load_from_replay(buffer)
        trainer.train_step()

        # 5️⃣ Update internal models via LearningEngine
        metrics = engine.run_epoch(trainer)
        tracker.record(metrics)

        # 6️⃣ Optimize fusion calibrations
        calibrator.optimize(metrics)

        # 7️⃣ Save model and log state
        models.save_checkpoint()
        log.record_cycle_summary(metrics)

        print("[LearningPipeline] ✅ Learning cycle complete and persisted.")

    except Exception as e:
        print("[LearningPipeline] ❌ Error during cycle:", e)
        traceback.print_exc()
