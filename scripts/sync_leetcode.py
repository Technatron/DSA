#!/usr/bin/env python3
# scripts/sync_leetcode.py
import os
import requests
import json
import time
from pathlib import Path

# ===== CONFIG =====
USERNAME = os.environ.get("LEETCODE_USERNAME")
SESSION_COOKIE = os.environ.get("LEETCODE_SESSION")
OUT_DIR = Path("leetcode")
STATE_FILE = Path(".leetcode_state.json")
PAGE_LIMIT = 50        # how many submissions to fetch per request (pagination)
ONLY_ACCEPTED = os.environ.get("ONLY_ACCEPTED", "1") == "1"  # default: only save Accepted solutions

if not USERNAME or not SESSION_COOKIE:
    raise SystemExit("Set LEETCODE_USERNAME and LEETCODE_SESSION in environment")

# language -> extension and comment prefix for header
LANG_EXT = {
    "python3": ("py", "#"),
    "python": ("py", "#"),
    "cpp": ("cpp", "//"),
    "c++": ("cpp", "//"),
    "java": ("java", "//"),
    "javascript": ("js", "//"),
    "js": ("js", "//"),
    "c": ("c", "//"),
    "c#": ("cs", "//"),
    "csharp": ("cs", "//"),
    "ruby": ("rb", "#"),
    "swift": ("swift", "//"),
    "go": ("go", "//"),
    "golang": ("go", "//"),
    "kotlin": ("kt", "//"),
    "scala": ("scala", "//"),
}

# ===== helper functions =====
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"processed_ids": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def make_header(prefix, title, slug, qid, sub_id, status, lang, runtime, memory, ts):
    timestr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    header_lines = [
        f"{prefix} Title: {title}",
        f"{prefix} URL: https://leetcode.com/problems/{slug}/",
        f"{prefix} Question ID: {qid}",
        f"{prefix} Submission ID: {sub_id}",
        f"{prefix} Status: {status}",
        f"{prefix} Language: {lang}",
        f"{prefix} Runtime: {runtime}",
        f"{prefix} Memory: {memory}",
        f"{prefix} Timestamp: {timestr}",
        "",
    ]
    return "\n".join(header_lines)

# ===== networking setup =====
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; leetcode-sync/1.0)",
    "Referer": "https://leetcode.com",
    "Accept": "application/json, text/plain, */*",
})
session.cookies.set("LEETCODE_SESSION", SESSION_COOKIE, domain=".leetcode.com")

# ===== fetch list of submissions (paginated) =====
def fetch_submission_pages():
    submissions = []
    offset = 0
    while True:
        url = f"https://leetcode.com/api/submissions/{USERNAME}/?offset={offset}&limit={PAGE_LIMIT}"
        r = session.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        page = data.get("submissions_dump", [])
        if not page:
            break
        submissions.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += len(page)
    return submissions

# ===== fetch submission detail (GraphQL) =====
GRAPHQL = """
query submissionDetail($submissionId: Int!) {
  submissionDetail(submissionId: $submissionId) {
    id
    code
    runtime
    memory
    statusDisplay
    lang
    timestamp
    question {
      title
      titleSlug
      questionFrontendId
    }
  }
}
"""

def fetch_submission_detail(submission_id):
    payload = {"query": GRAPHQL, "variables": {"submissionId": int(submission_id)}}
    r = session.post("https://leetcode.com/graphql", json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("submissionDetail")

# ===== main sync =====
def main():
    state = load_state()
    processed = set(state.get("processed_ids", []))

    print("Fetching submissions list...")
    subs = fetch_submission_pages()
    print(f"Total submissions fetched: {len(subs)}")

    # new submissions (IDs not processed yet)
    new_ids = [s["id"] for s in subs if str(s["id"]) not in processed]
    if not new_ids:
        print("No new submissions to process.")
        return

    print(f"New submissions to process: {len(new_ids)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # process oldest -> newest: reverse so earliest first
    for sid in reversed(new_ids):
        print(f"Fetching detail for submission: {sid}")
        try:
            detail = fetch_submission_detail(sid)
        except Exception as e:
            print(f"  error fetching detail {sid}: {e}")
            continue
        if not detail:
            print(f"  no detail for {sid}, skipping")
            continue

        status = detail.get("statusDisplay")
        if ONLY_ACCEPTED and status != "Accepted":
            print(f"  skipping submission {sid} with status {status}")
            processed.add(str(sid))
            continue

        question = detail.get("question") or {}
        title = question.get("title", "unknown-title")
        slug = question.get("titleSlug", f"unknown-{question.get('questionFrontendId','')}")
        qid = question.get("questionFrontendId", "")
        code = detail.get("code") or ""
        lang = (detail.get("lang") or "").lower()

        ext, comment_prefix = LANG_EXT.get(lang, ("txt", "//"))
        folder = OUT_DIR / f"{qid}_{slug}"
        folder.mkdir(parents=True, exist_ok=True)

        filename = folder / f"{qid}-{slug}-{sid}.{ext}"
        header = make_header(comment_prefix, title, slug, qid, sid, status, detail.get("lang"), detail.get("runtime"), detail.get("memory"), detail.get("timestamp") or int(time.time()))
        content = header + code

        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  saved: {filename}")

        processed.add(str(sid))
        # small delay to be polite
        time.sleep(0.4)

    # update and save state
    state["processed_ids"] = sorted(list(processed), key=int)
    save_state(state)
    print("Done. State updated.")

if __name__ == "__main__":
    main()
