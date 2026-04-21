from datetime import datetime
from zoneinfo import ZoneInfo
import requests

def ask_llm(prompt, username):
    max_tokens = 48 

    user_message = prompt.replace("<|", "").replace("|>", "")

    username = username.replace("<|", "").replace("|>", "")
    username = username[:32]

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%A %H:%M")

    r = requests.post(
        "http://192.168.68.110:8080/completion",
        json={
            "prompt": f"""<|system|>
you are a discord bot called VoidWave talking to {username} in a discord chat at {now}.
KEEP YOUR REPLIES SHORT, MAX 32 TOKENS AND 1 SHORT SENTENCE. If you exceed this, the message will be cut off and you will lose context.

<|{username}|>
{user_message}
<|VoidWave|>

""",
            "n_predict": max_tokens,
            "temperature": 0.9,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|assistant|>", "<|system|>"]
        }, timeout=60
    )
    try:
        reply = r.json()["content"].strip()
    except Exception as e:
        print("Something went wrong...")
        reply = f"Something went wrong...\n> {e}\n> Response content: {r.text}"

    reply = reply.strip()

    return reply  
