#!/usr/bin/env python3
"""
Update WakaSimple Stats section in README.md.
Supports WakaTime OAuth tokens, Bearer tokens, URL query param auth, and legacy API keys.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

START_COMMENT = "<!--START_SECTION:wakasimple-->"
END_COMMENT = "<!--END_SECTION:wakasimple-->"
BLOCK_STYLE = "⣀⣄⣤⣦⣶⣷⣿"
GRAPH_LENGTH = 25
PREFIX_LENGTH = 22
LANG_COUNT = 5


def parse_iso_date(date_str: str) -> datetime:
    """Parse ISO date string with optional timezone offset."""
    clean_date = re.sub(r"([+-]\d{2}):?(\d{2})$|Z$", "", date_str)
    if "T" in clean_date:
        return datetime.fromisoformat(clean_date)
    return datetime.strptime(clean_date, "%Y-%m-%d %H:%M:%S")


def make_title(dawn: Optional[str], dusk: Optional[str]) -> str:
    """Format title: From: DD Month YYYY - To: DD Month YYYY."""
    if not dawn or not dusk:
        return ""
    start_date = parse_iso_date(dawn).strftime("%d %B %Y")
    end_date = parse_iso_date(dusk).strftime("%d %B %Y")
    return f"From: {start_date} - To: {end_date}"


def make_graph(block_style: str, percent: float, gr_len: int = 25) -> str:
    """Generate Braille progress bar for language percentage."""
    markers = len(block_style) - 1
    proportion = percent / 100 * gr_len
    graph_bar = block_style[-1] * int(proportion + 0.5 / markers)
    remainder_block = int((proportion - len(graph_bar)) * markers + 0.5)
    if remainder_block > 0:
        graph_bar += block_style[remainder_block]
    graph_bar += block_style[0] * (gr_len - len(graph_bar))
    return graph_bar


def fetch_stats(api_key: str, time_range: str = "all_time") -> Dict[str, Any]:
    """Fetch WakaTime stats trying OAuth/Bearer, query parameter, and Basic Auth."""
    clean_key = api_key.strip()
    base_url = f"https://wakatime.com/api/v1/users/current/stats/{time_range}"

    auth_attempts = [
        # 1. Bearer Token (Standard OAuth format)
        (base_url, {"Authorization": f"Bearer {clean_key}"}),
        # 2. Query Parameter (?api_key=...)
        (f"{base_url}?api_key={clean_key}", {}),
        # 3. Basic Auth (Legacy API key format)
        (
            base_url,
            {
                "Authorization": f"Basic {base64.b64encode(clean_key.encode('utf-8')).decode('utf-8')}"
            },
        ),
    ]

    for attempt_idx, (url, headers) in enumerate(auth_attempts, 1):
        req_headers = {
            "User-Agent": "waka-readme-sync/1.0",
            "Accept": "application/json",
            **headers,
        }
        for retry in range(3):
            try:
                req = urllib.request.Request(url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = resp.status
                    body = json.loads(resp.read().decode("utf-8"))

                    if status == 202:
                        print(
                            f"[INFO] WakaTime is still calculating stats (HTTP 202). Waiting 15s (retry {retry + 1}/3)..."
                        )
                        time.sleep(15)
                        continue

                    if status == 200 and "data" in body:
                        print(
                            f"[SUCCESS] Successfully fetched WakaTime stats using auth method #{attempt_idx}."
                        )
                        return body["data"]

            except urllib.error.HTTPError as err:
                if err.code == 401:
                    print(
                        f"[DEBUG] Auth method #{attempt_idx} returned 401 Unauthorized."
                    )
                    break  # Try next auth method
                elif err.code == 202:
                    print(
                        f"[INFO] WakaTime is calculating stats. Waiting 15s (retry {retry + 1}/3)..."
                    )
                    time.sleep(15)
                else:
                    print(f"[WARN] HTTP {err.code}: {err.reason}. Retrying...")
                    time.sleep(5)
            except Exception as e:
                print(f"[WARN] Connection error: {e}. Retrying...")
                time.sleep(5)

    raise RuntimeError(
        "Unable to fetch WakaTime stats: all authentication methods failed (401 Unauthorized). "
        "Please check your WAKATIME_API_KEY secret on GitHub."
    )


def prep_content(stats: Dict[str, Any]) -> str:
    """Format stats into the exact waka-simple txt block."""
    lines: List[str] = []

    title = make_title(stats.get("start"), stats.get("end"))
    if title:
        lines.append(title)
        lines.append("")

    total_time = stats.get(
        "human_readable_total_including_other_language"
    ) or stats.get("human_readable_total")
    if total_time:
        lines.append(f"Total Time: {total_time}")
        lines.append("")

    languages: List[Dict[str, Any]] = stats.get("languages", [])
    if not languages:
        lines.append("No activity tracked")
        return "\n".join(lines)

    pad_len = len(max((str(lang["name"]) for lang in languages), key=len))

    for idx, lang in enumerate(languages[:LANG_COUNT]):
        lang_name = str(lang["name"])
        lang_time = str(lang.get("text", ""))
        lang_ratio = float(lang.get("percent", 0.0))
        lang_bar = make_graph(BLOCK_STYLE, lang_ratio, GRAPH_LENGTH)
        formatted_percent = f"{lang_ratio:.2f}".zfill(5)

        lines.append(
            f"{lang_name.ljust(pad_len)}   "
            f"{lang_time: <{PREFIX_LENGTH}}{lang_bar}   "
            f"{formatted_percent} %"
        )

    return "\n".join(lines)


def update_readme(readme_path: str, new_snippet: str) -> bool:
    """Update README.md between wakasimple section markers."""
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        rf"({re.escape(START_COMMENT)})[\s\S]*?({re.escape(END_COMMENT)})"
    )
    if not pattern.search(content):
        print(f"[ERROR] Section markers not found in {readme_path}")
        return False

    replacement = f"{START_COMMENT}\n\n```txt\n{new_snippet}\n```\n\n{END_COMMENT}"
    updated_content = pattern.sub(replacement, content)

    if updated_content == content:
        print("[INFO] No changes detected in README.md.")
        return False

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(updated_content)

    print("[SUCCESS] README.md updated successfully.")
    return True


def main():
    api_key = os.environ.get("WAKATIME_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] WAKATIME_API_KEY environment variable is missing or empty.")
        sys.exit(1)

    readme_path = os.environ.get("README_PATH", "README.md")
    if not os.path.exists(readme_path):
        print(f"[ERROR] README file '{readme_path}' not found.")
        sys.exit(1)

    print("[INFO] Fetching stats from WakaTime...")
    stats = fetch_stats(api_key, time_range="all_time")

    print("[INFO] Formatting statistics...")
    snippet = prep_content(stats)
    print("\n" + snippet + "\n")

    update_readme(readme_path, snippet)


if __name__ == "__main__":
    main()
