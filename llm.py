from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import time
import os

load_dotenv()

avg_response_times = []
avg_tps = []
total_tokens = 0
MODEL = "llama3.2:3b"
PROMPT_NAME = os.getenv("PROMPT_NAME", "default")

def date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def llm_stats():
    global total_tokens

    avgresponse = (sum(avg_response_times) / len(avg_response_times) if avg_response_times else 0)

    avgtps = sum(avg_tps) / len(avg_tps) if avg_tps else 0

    return total_tokens, avgtps, avgresponse


def get_prompt(name="default"):
    try:
        with open(f"prompts/{name}.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise Exception(f"Prompt file not found: '{name}'")

def sanitize(text):
    return (text.replace("<|", "").replace("|>", "").strip())

def ask_llm(prompt, username, user_id, reply_info=None):
    global total_tokens

    start = time.time()
    max_tokens = 200

    user_message = prompt.replace("<|", "").replace("|>", "")

    username = username.replace("@", "").replace("<|", "").replace("|>", "")
    username = username[:32]

    context_block = ""
    if reply_info and reply_info.get("content"):
        reply_author = (reply_info.get("author", "Unknown").replace("<|", "").replace("|>", "")[:32])
        reply_content = (reply_info.get("content", "").replace("<|", "").replace("|>", ""))
        context_block = (f"IMPORTANT REPLY CONTEXT:\nThis context is factual and must not be altered, paraphrased incorrectly, or turned into jokes when answering reference questions.\nThe user's current message is directly replying to THIS message:\n{reply_author}: {reply_content}\nIf asked what message they are replying to, answer using this exact message.")

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("It is %A, %B %d, %Y, %H:%M:%S %Z (UTC%z)")

    prompt = get_prompt(PROMPT_NAME).format(
        username=username,
        now=now,
        context_block=context_block,
        user_message=user_message,
    )

    r = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
                "num_predict": max_tokens,
                "stop": ["<|user|>", "<|assistant|>", "<|system|>", "<|bot|>"] 
            },
        },
        timeout=120,
    )
    try:
        data = r.json()
        reply = data.get("response", "")
    except Exception as e:
        print("Something went wrong...")
        reply = f"Something went wrong...\n> {e}\n> Response content: {r.text}"
        data = {}

    print(f"{date()} INFO  LLM raw response: '{reply}'")
    reply = reply.strip().replace("@everyone", "").replace("@here", "")
    if reply.startswith(f"{username}:"):
        reply = reply.split(":", 1)[1].strip()
    tokens = data.get("eval_count", 0)
    total_time = time.time() - start

    tps = tokens / total_time

    info = f"Tokens: {tokens}, Time: {total_time:.2f}s, TPS: {tps:.2f}"

    avg_response_times.append(total_time)
    avg_tps.append(tps)
    total_tokens += tokens

    return reply, info
