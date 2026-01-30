import os, json, time, hashlib, urllib.parse
import feedparser
import requests

BASE_WEBHOOK = os.environ.get("WEBHOOK_URL")
THREAD_ID = os.environ.get("THREAD_ID")
CATEGORY = os.environ.get("CATEGORY", "blogs")
FEEDS = json.loads(os.environ.get("FEED_URLS", "[]"))

STATE_PATH = f"cache/updates_{CATEGORY}.json"

def stable_id(entry):
  # prefer explicit ids, then link, then hashed title+published
  for k in ("id", "guid", "link"):
    v = getattr(entry, k, None)
    if v:
      return str(v)
  title = getattr(entry, "title", "")
  pub = getattr(entry, "published", "") or getattr(entry, "updated", "")
  return hashlib.sha256(f"{title}\n{pub}".encode("utf-8")).hexdigest()

def load_state():
  try:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
      return json.load(f)
  except FileNotFoundError:
    with open('STATE_PATH', 'w') as file:
      json.dump({}, file)
    return {}
  except json.JSONDecodeError:
    return {}

def save_state(state):
  os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
  with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

def thread_parse():
  if not BASE_WEBHOOK:
    raise RuntimeError("missing DISCORD_WEBHOOK")
  if not THREAD_ID:
    return BASE_WEBHOOK
  # append thread_id safely
  parsed = urllib.parse.urlparse(BASE_WEBHOOK)
  q = dict(urllib.parse.parse_qsl(parsed.query))
  q["thread_id"] = THREAD_ID
  return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(q)))

def discord_post(content):
  webhook_url = thread_parse()
  r = requests.post(webhook_url, json={"content": content}, timeout=20)
  r.raise_for_status()

def chunk_lines(lines, max_chars=1950): # discord hard limit is 2000; keep margin
  out, cur = [], ""
  for ln in lines:
    add = (ln + "\n")
    if len(cur) + len(add) > max_chars and cur:
      out.append(cur.rstrip())
      cur = ""
    cur += add
  if cur.strip():
    out.append(cur.rstrip())
  return out

def main():
  state = load_state()
  seen = set(state.get("seen_ids", []))

  new_items = []
  for url in FEEDS:
    f = feedparser.parse(url)
    for e in f.entries[:50]:
      sid = stable_id(e)
      if sid in seen:
        continue
      title = getattr(e, "title", "(no title)")
      link = getattr(e, "link", "")
      description = getattr(e, "description", None)
      new_items.append((sid, title, link, description))

  if not new_items:
    print("no new items")
    return

  # mark seen before posting to avoid duplicate spam if discord call retries mid-run
  for sid, _, _, _ in new_items:
    seen.add(sid)

  lines = [f"- [{title}]({link}){f': {description}' if description else ''}".strip() for _, title, link, description in new_items[:50]]
  header = f"RSS update ({len(new_items)} new entries):"
  chunks = chunk_lines([header] + lines)

  for msg in chunks:
    discord_post(msg)

  state["updated_at"] = int(time.time())
  state["seen_ids"] = list(seen)[-5000:]  # cap growth
  save_state(state)
  print(f"posted {len(new_items)} new items")

if __name__ == "__main__":
  main()
