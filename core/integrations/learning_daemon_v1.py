import time
from core.integrations.learning_pipeline_v1 import run_learning_cycle

def run_daemon(interval=3600):
    print(f"[LearningDaemon] 🧠 Running continuous learning every {interval/60:.1f} minutes.")
    while True:
        run_learning_cycle()
        time.sleep(interval)

if __name__ == "__main__":
    run_daemon()
