from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import time

history = {}

def date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_prompt(name="default"):
    try:
        with open(f"prompts/{name}.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise Exception(f"Prompt file not found: '{name}'")


def ask_llm(prompt, username, user_id, reply_info = None):
    start = time.time()
    max_tokens = 1000

    user_message = prompt.replace("<|", "").replace("|>", "")

    username = username.replace("@", "").replace("<|", "").replace("|>", "")
    username = username[:32]

    context_block = ""
    if reply_info and reply_info.get("content"):
        reply_author = reply_info.get("author", "Unknown").replace("<|", "").replace("|>", "")[:32]
        reply_content = reply_info.get("content", "").replace("<|", "").replace("|>", "")
        context_block = f"{username} is replying to a message:\n{reply_author}: {reply_content}"

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("It is %A, %B %d, %Y, %H:%M:%s")

    prompt = get_prompt("default").format(username=username, now=now, context_block=context_block, user_message=user_message)
    print(context_block)
    r = requests.post(
        "http://localhost:8080/completion",
        json={
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": 0.3,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|assistant|>", "<|system|>", "<|bot|>", "\n"]
        }, timeout=120
    )
    try:
        data = r.json()
        reply = data["content"]
    except Exception as e:
        print("Something went wrong...")
        reply = f"Something went wrong...\n> {e}\n> Response content: {r.text}"
        data = {}

    print(f"{date()} INFO  LLM raw response: '{reply}'")
    reply = reply.strip()
    tokens = data.get('tokens_predicted', 0)
    total_time = time.time() - start

    tps = tokens / total_time 

    info = f"Tokens: {tokens}, Time: {total_time:.2f}s, TPS: {tps:.2f}"
    print(prompt)
    return reply, info
