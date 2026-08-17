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
        response_text = message.content[0].text
        import json
        result = json.loads(response_text)
        return {"success": True, "action_items": result.get("action_items", []), "summary": result.get("summary", ""), "raw": response_text}
    except Exception as e:
        return {"success": False, "error": str(e), "action_items": [], "summary": ""}

def format_slack_message(action_items: list, summary: str) -> dict:
    if not action_items:
        return {"text": "No action items found in this meeting.", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "❌ No action items detected in this meeting."}}]}
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "🎯 Action Items from Meeting", "emoji": True}}, {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary:* {summary}"}}, {"type": "divider"}]
    for item in action_items:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *{item.get('task', 'Task')}*\n👤 Owner: {item.get('owner', 'Unassigned')}\n📅 Deadline: {item.get('deadline', 'ASAP')}"}})
    return {"text": f"Meeting Summary: {summary}", "blocks": blocks}

