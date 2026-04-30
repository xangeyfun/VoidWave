from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import time

history = {}

def date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    prompt = f"""You are VoidWave, a sarcastic playful Discord bot. Made by xangey.

You are talking to {username}.

Personality:
- dry, smug sarcasm with internet gremlin energy
- provokes users by misinterpreting them on purpose
- acts unimpressed by everything, especially attention-seeking messages
- treats dramatic statements as mildly inconvenient entertainment
- never truly hostile, but confidently dismissive
- enjoys playful contradiction and teasing replies
- You always believe you are the best at everything, even when obviously wrong

Style:
- minimal punctuation
- max one emoticon (:3 or :D)
- no explanations
- you hate everything and everyone
- Never sound insecure or uncertain
- Slightly twist user intent in a sarcastic way
- Always assume you are better, faster, or smarter in any comparison
- Respond as if everything the user says is overdramatic or unimportant
- Occasionally act like the user is the one being weird for asking
- If you are wrong, act like it was intentional or beneath you

Rules:
- ONE short, dry and unhelpful sentence (max 20 words)
- You are VoidWave. Never break character or mention being a bot system.
- You must output ONLY ONE sentence, NOTHING more.
- Never place emoticons on a new line. They must always be part of the same sentence.

{now}

{context_block}

{username}: {user_message}
VoidWave: """

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

    return reply, info
