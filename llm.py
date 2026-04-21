from datetime import datetime
from zoneinfo import ZoneInfo
import requests

def ask_llm(prompt, username):
    max_tokens = 64

    user_message = prompt.replace("<|", "").replace("|>", "")

    username = username.replace("<|", "").replace("|>", "")
    username = username[:32]

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%A %H:%M")

    r = requests.post(
        "http://192.168.68.110:8080/completion",
        json={
            "prompt": f"""<|system|>
You are a casual Discord user chatting with {username} at {now}.

Rules (highest priority):
- Reply with ONE short sentence (max 20 words)
- Be casual and playful
- Use at most one text emoticon like :3 or :D, or none
- Do not mention being a bot, assistant, or any role
- Do not add explanations, notes, or side comments
- Do not use emojis (only text emoticons allowed)
- Mention {username} only if natural
- Keep replies in a single sentence on one line.

<|user|>
{user_message}
<|assistant|>
""",
            "n_predict": max_tokens,
            "temperature": 0.5,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|assistant|>", "<|system|>", "<|bot|>", "\n"]
        }, timeout=120
    )
    try:
        reply = r.json()["content"].strip()
    except Exception as e:
        print("Something went wrong...")
        reply = f"Something went wrong...\n> {e}\n> Response content: {r.text}"

    reply = reply.strip()

    return reply  
