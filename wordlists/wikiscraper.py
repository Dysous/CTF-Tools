import requests
from bs4 import BeautifulSoup

URL = "https://en.wikipedia.org/wiki/List_of_Game_Boy_games"

# 1) Fetch with a desktop User-Agent + sanity checks
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
resp = requests.get(URL, headers=headers, timeout=20)
resp.raise_for_status()

# Optional: see what we actually got
print("HTTP", resp.status_code, "bytes:", len(resp.text))

# 2) Parse the HTML text (not .content) to avoid odd warnings
soup = BeautifulSoup(resp.text, "html.parser")

# 3) Find ALL wikitables (there are many on this page, A–Z)
tables = soup.select("table.wikitable")
if not tables:
    # Dump a short snippet to diagnose what came back
    print("No tables found. First 400 chars of page:\n", resp.text[:400])
    raise SystemExit(1)

# 4) Extract the first column (game title) from every table
wordlist = []
for tbl in tables:
    rows = tbl.find_all("tr")
    if not rows:
        continue
    # Try to detect header and skip it
    start_idx = 1 if rows[0].find_all(["th", "td"]) else 0
    for row in rows[start_idx:]:
        cells = row.find_all("td")
        if not cells:
            continue
        title = cells[0].get_text(strip=True)
        if title:
            wordlist.append(title)

# 5) (Optional) de-dupe + sort for a cleaner list
wordlist = sorted(set(wordlist), key=str.casefold)

out_path = r"C:\Users\NTMat\Downloads\wordlist.txt"
with open(out_path, "w", encoding="utf-8") as f:
    for w in wordlist:
        f.write(w + "\n")

print(f"Wrote {len(wordlist)} titles to {out_path}")
