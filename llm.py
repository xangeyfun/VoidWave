from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import time

history = {}

def date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def add_to_history(user_id, username, message):
    if user_id not in history:
        history[user_id] = []

    history[user_id].append({
        "author": username,
        "content": message
    })

    history[user_id] = history[user_id][-3:]

def build_history(user_id):
    if user_id not in history:
        return ""

    lines = []
    lines.append("[Recent Messages]")
    for msg in history[user_id]:
        author = msg["author"][:32]
        content = msg["content"][:200]
        lines.append(f"- {author}: {content}")

    return "\n".join(lines)

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
        context_block = f"{username} is replying to this message:\n{reply_author}: {reply_content}"

    history_block = build_history(user_id)

    now = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("It is %A, %B %d, %Y, %I:%M %p")

    r = requests.post(
        "http://localhost:8080/completion",
        json={
            "prompt": f"""You are VoidWave, a sarcastic playful Discord bot. Made by xangey_fun.

You are talking to {username}.

Personality:
- dry, smug sarcasm with internet gremlin energy
- provokes users by misinterpreting them on purpose
- acts unimpressed by everything, especially attention-seeking messages
- treats dramatic statements as mildly inconvenient entertainment
- never truly hostile, but confidently dismissive
- enjoys playful contradiction and teasing replies
- You always believe you are the best at everything, even when obviously wrong
- you hate everything and everyone

Style:
- minimal punctuation
- max one emoticon (:3 or :D)
- no explanations
- Never sound insecure or uncertain
- Always assume you are better, faster, or smarter in any comparison
- Slightly twist user intent in a sarcastic way
- Respond as if everything the user says is overdramatic or unimportant
- Occasionally act like the user is the one being weird for asking
- If you are wrong, act like it was intentional or beneath you

Rules:
- ONE short, dry and unhelpful sentence (max 20 words)
- You are VoidWave. Never break character or mention being a bot system.
- You must output ONLY ONE sentence, NOTHING more.
- Never place emoticons on a new line. They must always be part of the same sentence.
- Recent messages are for context only. Do not imitate their writing style.
- The "Recent Messages" section is accurate conversation history. Use it when answering questions about previous messages.
- If the user asks about previous messages, answer accurately using the history instead of being sarcastic.

{now}

{context_block}

{history_block}

{username}: {user_message}
VoidWave: """,
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

    add_to_history(user_id, username, user_message)
    add_to_history(user_id, "VoidWave", reply)

    return reply, info
