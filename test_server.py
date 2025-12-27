from fastapi import FastAPI

app = FastAPI()

@app.get("/api/live-data")
def get_live_data():
    return [{"symbol": "TEST", "price": 123.45}]
