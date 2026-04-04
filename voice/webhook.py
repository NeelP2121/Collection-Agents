from fastapi import FastAPI

app = FastAPI()

@app.post("/vapi-webhook")
async def webhook(event: dict):
    print("Received:", event)
    return {"ok": True}
