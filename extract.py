import os
from anthropic import Anthropic

# Initialize client with API key from environment
# Try ANTHROPIC_API_KEY first (standard), then fall back to CLAUDE_API_KEY
api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    api_key = os.getenv("CLAUDE_API_KEY")

if api_key:
    client = Anthropic(api_key=api_key)
else:
    # If no API key found, Anthropic SDK will look for default env vars
    client = Anthropic()

def extract_action_items(transcript: str) -> dict:
    """
    Extract action items from meeting transcript using Claude.
    Returns: {
        "action_items": [{"task": str, "owner": str, "deadline": str}],
        "summary": str
    }
    """
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze this meeting transcript and extract ALL action items.

TRANSCRIPT:
{transcript}

RESPONSE FORMAT (JSON):
{{
  "action_items": [
    {{"task": "specific action", "owner": "person name or 'Unassigned'", "deadline": "date or 'ASAP'"}},
    ...
  ],
  "summary": "1-line meeting summary"
}}

Extract ONLY action items (specific tasks with owners). Be strict - no vague items.
Return ONLY valid JSON, no other text."""
                }
            ]
        )

        # Parse response
        response_text = message.content[0].text

        # Try to parse as JSON.
        # Claude a veces envuelve el JSON en un bloque ```json ... ```
        # o agrega texto antes/despues. Extraemos el objeto JSON real.
        import json, re
        cleaned = response_text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()
        else:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end > start:
                cleaned = cleaned[start:end + 1]
        result = json.loads(cleaned)

        return {
            "success": True,
            "action_items": result.get("action_items", []),
            "summary": result.get("summary", ""),
            "raw": response_text
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "action_items": [],
            "summary": ""
        }

def format_slack_message(action_items: list, summary: str) -> dict:
    """
    Format action items for Slack message.
    Returns formatted Slack message payload.
    """
    if not action_items:
        return {
            "text": "No action items found in this meeting.",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "❌ No action items detected in this meeting."
                    }
                }
            ]
        }

    # Build blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🎯 Action Items from Meeting",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary:* {summary}"
            }
        },
        {
            "type": "divider"
        }
    ]

    # Add each action item
    for item in action_items:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"✅ *{item.get('task', 'Task')}*\n👤 Owner: {item.get('owner', 'Unassigned')}\n📅 Deadline: {item.get('deadline', 'ASAP')}"
            }
        })

    return {
        "text": f"Meeting Summary: {summary}",
        "blocks": blocks
    }

# Redeploy trigger
