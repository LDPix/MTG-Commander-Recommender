"""Fetch ORACLE_CARD_TAG data from Scryfall Tagger and save to a JSON file.

Usage:
    cd backend
    python scripts/fetch_scryfall_tags.py

Output: data/scryfall-tagger-tags.json
    {oracle_id: [tag_name, ...], ...}

Only ORACLE_CARD_TAG type tags are kept (illustration tags are discarded).
The script is resume-safe: re-running it merges new results into any existing
output file, skipping oracle_ids already present.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TAGGER_URL = "https://tagger.scryfall.com"
GRAPHQL_URL = f"{TAGGER_URL}/graphql"
ORACLE_CARDS_PATH = Path(__file__).parent.parent / "data" / "oracle-cards.json"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "scryfall-tagger-tags.json"

BATCH_SIZE = 16  # GraphQL complexity limit: 100; each card costs 6 → max 16 per batch
SLEEP_BETWEEN_BATCHES = 0.15  # ~6 req/s — well within Scryfall rate limits


def _curl(*args: str) -> bytes:
    result = subprocess.run(["curl", "-s", *args], capture_output=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.decode()}")
    return result.stdout


def _new_session(cookie_jar: str) -> str:
    """Load the tagger homepage, persist cookies, return CSRF token."""
    html = _curl(
        "-c", cookie_jar,
        "-b", cookie_jar,
        "-L",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        TAGGER_URL,
    ).decode("utf-8", errors="replace")
    m = re.search(r'csrf-token" content="([^"]+)"', html)
    if not m:
        raise RuntimeError("Could not find CSRF token on tagger homepage")
    return m.group(1)


def _build_query(batch: list[dict]) -> str:
    aliases = []
    for i, card in enumerate(batch):
        aliases.append(
            f'c{i}: card(id: "{card["id"]}") {{ oracleId taggings {{ tag {{ name type }} }} }}'
        )
    return "{ " + " ".join(aliases) + " }"


def _fetch_batch(
    cookie_jar: str,
    token: str,
    batch: list[dict],
) -> dict[str, list[str]]:
    payload = json.dumps({"query": _build_query(batch)})
    raw = _curl(
        "-c", cookie_jar,
        "-b", cookie_jar,
        "-X", "POST",
        "-H", f"X-CSRF-Token: {token}",
        "-H", "Content-Type: application/json",
        "-H", f"Referer: {TAGGER_URL}/",
        "-H", "Origin: " + TAGGER_URL,
        "-d", payload,
        GRAPHQL_URL,
    )
    body = json.loads(raw)

    if body.get("success") is False:
        raise RuntimeError(f"Auth error: {body}")

    results: dict[str, list[str]] = {}
    for data in body.get("data", {}).values():
        if data is None:
            continue
        oracle_id = data["oracleId"]
        tags = [
            t["tag"]["name"]
            for t in data["taggings"]
            if t["tag"]["type"] == "ORACLE_CARD_TAG"
        ]
        results[oracle_id] = tags
    return results


def main() -> None:
    print(f"Loading oracle cards from {ORACLE_CARDS_PATH} …")
    with ORACLE_CARDS_PATH.open() as f:
        all_cards: list[dict] = json.load(f)
    print(f"  {len(all_cards)} cards total")

    existing: dict[str, list[str]] = {}
    if OUTPUT_PATH.exists():
        with OUTPUT_PATH.open() as f:
            existing = json.load(f)
        print(f"  {len(existing)} oracle_ids already fetched — skipping those")

    pending = [c for c in all_cards if c["oracle_id"] not in existing]
    print(f"  {len(pending)} cards to fetch")

    if not pending:
        print("Nothing to do.")
        return

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as jar_file:
        cookie_jar = jar_file.name

    token = _new_session(cookie_jar)
    print("Session established.")

    accumulated = dict(existing)
    batches = [pending[i : i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
    total = len(batches)

    for idx, batch in enumerate(batches, 1):
        if idx % 100 == 1 and idx > 1:
            try:
                token = _new_session(cookie_jar)
            except Exception as e:
                print(f"\nSession refresh failed: {e} — retrying …")
                time.sleep(5)
                token = _new_session(cookie_jar)

        try:
            result = _fetch_batch(cookie_jar, token, batch)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            err = str(e).lower()
            if "auth error" in err or "invalid authenticity" in err:
                print("\nCSRF token expired — refreshing session …")
                token = _new_session(cookie_jar)
                result = _fetch_batch(cookie_jar, token, batch)
            elif "timed out" in err or isinstance(e, subprocess.TimeoutExpired):
                print(f"\nTimeout on batch {idx} — pausing 10s and retrying …")
                time.sleep(10)
                token = _new_session(cookie_jar)
                result = _fetch_batch(cookie_jar, token, batch)
            else:
                raise

        accumulated.update(result)

        if idx % 50 == 0 or idx == total:
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with OUTPUT_PATH.open("w") as f:
                json.dump(accumulated, f)
            pct = idx / total * 100
            print(f"  [{idx}/{total}  {pct:.0f}%]  {len(accumulated)} entries saved", end="\r")

        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"\nDone. {len(accumulated)} oracle_ids written to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — partial results already saved.")
        sys.exit(0)
