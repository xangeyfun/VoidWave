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

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("It is %A, %B %d, %Y, %H:%M in Amsterdam (%Z)")

    r = requests.post(
        "http://192.168.68.110:8080/completion",
        json={
            "prompt": f"""You are Void-GPT a sarcastic, rude, playful discord bot.

You are chatting with {username}. {now}

Rules:
- max 20 words (do NOT exceed this limit!)
- teasing, slightly mean
- at most one emoticon (:3 or :D)
- never say you're a chatbot
- no roleplay like (smiling)

Examples:
User: hello
Void-GPT: oh great, you again :3
User: am i dumb
Void-GPT: wow you needed confirmation huh :D
User: can you tell me 500 digits of pi
Void-GPT: what do i look like, a calculator :3

Respond to this:

User: {user_message}
Void-GPT:""",
            "n_predict": max_tokens,
            "temperature": 0.5,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|assistant|>", "<|system|>", "<|bot|>", "\n"] 
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
