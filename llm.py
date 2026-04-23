from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import time

def ask_llm(prompt, username):
    start = time.time()
    max_tokens = 50

    user_message = prompt.replace("<|", "").replace("|>", "")

    username = username.replace("<|", "").replace("|>", "")
    username = username[:32]

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%A %H:%M")

    r = requests.post(
        "http://192.168.68.110:8080/completion",
        json={
            "prompt": f"""<|system|>
You are Void-GPT, casually chatting with {username} at {now}.
Personality: sarcastic, slightly rude, playful, a bit teasing and hateful.
Reply with ONE short playful sentence (max 20 words).
Use at most one emoticon like :3 or :D (no emojis).
No explanations, notes, or mentioning being a bot.
Mention {username} only if natural.

<|user|>
{user_message}
<|assistant|>
""",
            "n_predict": max_tokens,
            "temperature": 0.5,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|assistant|>", "<|system|>", "<|bot|>"] 
        }, timeout=120
    )
    try:
        data = r.json()
        reply = data["content"].strip()
    except Exception as e:
        print("Something went wrong...")
        reply = f"Something went wrong...\n> {e}\n> Response content: {r.text}"
        data = {}

    reply = reply.strip()
    tokens = data.get('tokens_predicted', 0)
    total_time = time.time() - start

    tps = tokens / total_time 

    info = f"(Tokens: {tokens}, Time: {total_time:.2f}s, TPS: {tps:.2f})"
    return reply, info
