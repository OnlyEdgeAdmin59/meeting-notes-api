from fastapi import FastAPI, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import requests
from extract import extract_action_items, format_slack_message
from typing import Optional

app = FastAPI(title="Meeting Notes API")

# Serve static files
app.mount("/static", StaticFiles(directory="public"), name="static")

# Environment variables
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

@app.get("/")
async def root():
    """Serve test page"""
    return FileResponse("public/test.html")

@app.post("/api/extract")
async def extract(transcript: str = Form(...), webhook_url: Optional[str] = Form(None)):
    """Extract action items from transcript and send to Slack."""
    
    webhook = webhook_url or SLACK_WEBHOOK_URL

    if not webhook:
        return JSONResponse(
            {"success": False, "error": "Slack webhook URL not configured"},
            status_code=400
        )

    extraction = extract_action_items(transcript)

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
        "slack_sent": slack_sent,
        "slack_status": response.status_code if response else "error"
    }

@app.post("/api/test")
async def test_webhook(webhook_url: Optional[str] = Form(None)):
    """Test Slack webhook."""
    webhook = webhook_url or SLACK_WEBHOOK_URL

    if not webhook:
        return JSONResponse(
            {"success": False, "error": "No webhook URL provided"},
            status_code=400
        )

    test_message = {
        "text": "🧪 Test message from Meeting Notes Bot",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "✅ *Slack integration is working!*"
                }
            }
        ]
    }

    try:
        response = requests.post(webhook, json=test_message, timeout=5)
        success = response.status_code == 200
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=400
        )

    return {
        "success": success,
        "status_code": response.status_code,
        "message": "Test message sent" if success else "Failed"
    }

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "version": "0.1.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
