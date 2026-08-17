from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import requests
from extract import extract_action_items, format_slack_message
from typing import Optional

app = FastAPI(title="Meeting Notes API")
app.mount("/static", StaticFiles(directory="public"), name="static")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

@app.get("/")
async def root():
    return FileResponse("public/index.html")

@app.post("/api/extract")
async def extract(transcript: str = Form(...), webhook_url: Optional[str] = Form(None)):
    webhook = webhook_url or SLACK_WEBHOOK_URL
    if not webhook:
        return JSONResponse({"success": False, "error": "Slack webhook URL not configured"}, status_code=400)
    extraction = extract_action_items(transcript)
    if not extraction["success"]:
        return JSONResponse({"success": False, "error": extraction["error"]}, status_code=400)
    slack_message = format_slack_message(extraction["action_items"], extraction["summary"])
    try:
        response = requests.post(webhook, json=slack_message, timeout=5)
        slack_sent = response.status_code == 200
    except Exception as e:
        slack_sent = False
    return {"success": True, "action_items": extraction["action_items"], "summary": extraction["summary"], "slack_sent": slack_sent, "slack_status": response.status_code if slack_sent else "failed"}

@app.post("/api/test")
async def test_webhook(webhook_url: Optional[str] = Form(None)):
    webhook = webhook_url or SLACK_WEBHOOK_URL
    if not webhook:
        return JSONResponse({"success": False, "error": "No webhook URL provided"}, status_code=400)
    test_message = {"text": "🧪 Test message from Meeting Notes Bot", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "✅ *Slack integration is working!*\n\nThis is a test message from Meeting Notes Bot."}}]}
    try:
        response = requests.post(webhook, json=test_message, timeout=5)
        success = response.status_code == 200
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    return {"success": success, "status_code": response.status_code, "message": "Test message sent to Slack" if success else "Failed to send test message"}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
