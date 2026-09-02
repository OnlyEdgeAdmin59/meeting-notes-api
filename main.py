from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import os
import requests
from extract import extract_action_items, format_slack_message

app = FastAPI(title="Meeting Notes API")

# Serve static files
app.mount("/static", StaticFiles(directory="public"), name="static")

# Environment variables
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

class ExtractRequest(BaseModel):
    transcript: str
    webhook_url: Optional[str] = None

class TestRequest(BaseModel):
    webhook_url: Optional[str] = None

@app.get("/")
async def root():
    return FileResponse("public/test.html")

@app.post("/api/extract")
async def extract(request: ExtractRequest):
    webhook = request.webhook_url or SLACK_WEBHOOK_URL

    if not webhook:
        return JSONResponse(
            {"success": False, "error": "Slack webhook URL not configured"},
            status_code=400
        )

    extraction = extract_action_items(request.transcript)

    if not extraction["success"]:
        return JSONResponse(
            {"success": False, "error": extraction["error"]},
            status_code=400
        )

    slack_message = format_slack_message(
        extraction["action_items"],
        extraction["summary"]
    )

    response = None
    slack_sent = False
    
    try:
        response = requests.post(webhook, json=slack_message, timeout=5)
        slack_sent = response.status_code == 200
    except Exception as e:
        slack_sent = False

    return {
        "success": True,
        "action_items": extraction["action_items"],
        "summary": extraction["summary"],
        "slack_sent": slack_sent
    }

@app.post("/api/test")
async def test_webhook(request: Optional[TestRequest] = None):
    webhook = (request.webhook_url if request else None) or SLACK_WEBHOOK_URL

    if not webhook:
        return {"success": False, "error": "No webhook URL"}

    test_message = {
        "text": "🧪 Test message from Meeting Notes Bot",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "✅ Working!"}}]
    }

    try:
        response = requests.post(webhook, json=test_message, timeout=5)
        return {"success": response.status_code == 200, "status_code": response.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
