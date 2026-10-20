#!/usr/bin/env python3
"""Generate profile analytics cards from GitHub's public repository APIs."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


OWNER = "khairbakshnoor-pixel"
API_ROOT = "https://api.github.com"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "assets"
CACHE_DIR = Path(
    os.environ.get(
        "PROFILE_API_CACHE",
        str(Path(tempfile.gettempdir()) / f"{OWNER}-profile-api-cache"),
    )
)
COLORS = {
    "Python": "#3776AB",
    "Java": "#ED8B00",
    "JavaScript": "#E3B341",
    "TypeScript": "#3178C6",
    "C": "#5C6BC0",
    "C++": "#00599C",
    "HTML": "#E34F26",
    "CSS": "#663399",
    "Jupyter Notebook": "#DA5B0B",
    "SQL": "#336791",
    "Shell": "#89E051",
    "Go": "#00ADD8",
    "Kotlin": "#7F52FF",
    "Swift": "#F05138",
    "PHP": "#777BB4",
    "Ruby": "#CC342D",
}
FALLBACK_COLOR = "#8B5CF6"
BACKGROUND = "#0B0F19"
CARD = "#111827"
TEXT = "#F8FAFC"
MUTED = "#AAB6C5"
GOLD = "#D4AF37"
CYAN = "#20D9FF"
CACHE_HITS = 0


def api_get(path: str) -> Any:
    """Fetch one GitHub API resource with bounded retries and clear failures."""
    global CACHE_HITS
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{hashlib.sha256(path.encode('utf-8')).hexdigest()}.json"
    cached: dict[str, Any] | None = None
    if cache_file.exists():
        try:
            loaded = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "data" in loaded:
                cached = loaded
        except (OSError, json.JSONDecodeError):
            cached = None

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "khairbakshnoor-pixel-profile-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cached and isinstance(cached.get("etag"), str):
        headers["If-None-Match"] = cached["etag"]
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
                cache_entry = {"etag": response.headers.get("ETag"), "data": data}
                temporary = cache_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(cache_entry), encoding="utf-8")
                temporary.replace(cache_file)
                return data
        except urllib.error.HTTPError as error:
            if error.code == 304 and cached:
                CACHE_HITS += 1
                return cached["data"]
            if error.code in {403, 429}:
                retry_after = error.headers.get("Retry-After")
                reset_at = error.headers.get("X-RateLimit-Reset")
                if retry_after:
                    delay = max(1, int(retry_after))
                elif error.headers.get("X-RateLimit-Remaining") == "0" and reset_at:
                    delay = max(1, int(reset_at) - int(time.time()))
                else:
                    delay = 0
                if delay and delay <= 60 and attempt < 2:
                    time.sleep(delay)
                    continue
                if delay:
                    raise RuntimeError(
                        f"GitHub API rate limit reached for {path}; retry after {delay} seconds"
                    ) from error
            if error.code in {500, 502, 503, 504} and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(
                f"GitHub API request failed ({error.code}) for {path}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"GitHub API request failed for {path}: {error}") from error
    raise RuntimeError(f"GitHub API request exhausted retries for {path}")


def get_repositories() -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {"type": "owner", "per_page": 100, "page": page, "sort": "pushed"}
        )
        batch = api_get(f"/users/{OWNER}/repos?{query}")
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repository response")
        if not batch:
            break
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    eligible = [
        repo
        for repo in repositories
        if repo.get("owner", {}).get("login", "").casefold() == OWNER.casefold()
        and repo.get("private") is False
        and repo.get("fork") is False
        and repo.get("archived") is False
    ]
    return eligible


def get_language_bytes(repo: dict[str, Any]) -> dict[str, int]:
    name = repo.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("GitHub returned a repository without a valid name")
    languages = api_get(f"/repos/{OWNER}/{urllib.parse.quote(name, safe='')}/languages")
    if not isinstance(languages, dict):
        raise RuntimeError(f"Unexpected language response for repository {name}")
    return {
        language: amount
        for language, amount in languages.items()
        if isinstance(language, str) and isinstance(amount, int) and amount > 0
    }


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def write_stats_svg(repositories: list[dict[str, Any]], generated: dt.datetime) -> None:
    stars = sum(int(repo.get("stargazers_count") or 0) for repo in repositories)
    recent = sorted(
        (
            repo
            for repo in repositories
            if isinstance(repo.get("pushed_at"), str)
        ),
        key=lambda repo: repo["pushed_at"],
        reverse=True,
    )[:3]
    timestamp = generated.strftime("%d %b %Y · %H:%M UTC")

    rows = []
    for index, repo in enumerate(recent):
        pushed = dt.datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        rows.append(
            f'<text x="48" y="{208 + index * 28}" fill="{TEXT}" '
            f'font-family="Segoe UI,Arial,sans-serif" font-size="15">'
            f'{escape(repo["name"])}</text>'
            f'<text x="812" y="{208 + index * 28}" text-anchor="end" fill="{MUTED}" '
            f'font-family="Segoe UI,Arial,sans-serif" font-size="13">'
            f'{pushed.strftime("%d %b %Y")}</text>'
        )

    content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="880" height="310" viewBox="0 0 880 310" role="img" aria-labelledby="title description">
  <title id="title">Public GitHub repository snapshot</title>
  <desc id="description">{len(repositories)} eligible public repositories and {stars} stars, with the three most recently pushed repositories.</desc>
  <rect width="880" height="310" rx="20" fill="{BACKGROUND}"/>
  <rect x="1" y="1" width="878" height="308" rx="19" fill="none" stroke="#263244"/>
  <text x="32" y="42" fill="{GOLD}" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700" letter-spacing="2">PUBLIC REPOSITORY SNAPSHOT</text>
  <rect x="32" y="62" width="386" height="82" rx="12" fill="{CARD}"/>
  <rect x="432" y="62" width="416" height="82" rx="12" fill="{CARD}"/>
  <text x="52" y="98" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="13">ELIGIBLE PUBLIC REPOSITORIES</text>
  <text x="52" y="128" fill="{TEXT}" font-family="Segoe UI,Arial,sans-serif" font-size="28" font-weight="700">{len(repositories)}</text>
  <text x="452" y="98" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="13">STARS ON ELIGIBLE REPOSITORIES</text>
  <text x="452" y="128" fill="{TEXT}" font-family="Segoe UI,Arial,sans-serif" font-size="28" font-weight="700">{stars}</text>
  <text x="48" y="178" fill="{CYAN}" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700" letter-spacing="1.5">MOST RECENTLY PUSHED</text>
  {''.join(rows) if rows else f'<text x="48" y="215" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="14">No public repository push dates available.</text>'}
  <text x="832" y="291" text-anchor="end" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">Updated {escape(timestamp)} · Forks and archived repositories excluded</text>
</svg>
"""
    (OUTPUT_DIR / "stats.svg").write_text(content, encoding="utf-8")


def write_languages_svg(language_bytes: dict[str, int], generated: dt.datetime) -> None:
    total = sum(language_bytes.values())
    timestamp = generated.strftime("%d %b %Y · %H:%M UTC")
    if total <= 0:
        content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="880" height="190" viewBox="0 0 880 190" role="img" aria-labelledby="title description">
  <title id="title">GitHub-detected repository language distribution</title>
  <desc id="description">No language byte data is currently available from GitHub.</desc>
  <rect width="880" height="190" rx="20" fill="{BACKGROUND}"/>
  <rect x="1" y="1" width="878" height="188" rx="19" fill="none" stroke="#263244"/>
  <text x="32" y="42" fill="{GOLD}" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700" letter-spacing="2">LANGUAGES &amp; TECHNOLOGY ANALYTICS</text>
  <text x="32" y="91" fill="{TEXT}" font-family="Segoe UI,Arial,sans-serif" font-size="17">GitHub has not reported usable language bytes for these repositories yet.</text>
  <text x="32" y="126" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="13">Language data will appear after repositories contain detectable source code.</text>
  <text x="832" y="169" text-anchor="end" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">Updated {escape(timestamp)} · Code bytes, not skill proficiency</text>
</svg>
"""
        (OUTPUT_DIR / "languages.svg").write_text(content, encoding="utf-8")
        return

    ranked = sorted(language_bytes.items(), key=lambda item: (-item[1], item[0].casefold()))
    visible = ranked[:7]
    remainder = sum(amount for _, amount in ranked[7:])
    if remainder:
        visible.append(("Other", remainder))
    percentages = [amount * 100 / total for _, amount in visible]

    rows = []
    for index, ((language, _), percentage) in enumerate(zip(visible, percentages)):
        y = 102 + index * 31
        color = COLORS.get(language, FALLBACK_COLOR)
        label = f"{percentage:.1f}%"
        rows.append(
            f'<circle cx="48" cy="{y - 5}" r="5" fill="{color}"/>'
            f'<text x="64" y="{y}" fill="{TEXT}" font-family="Segoe UI,Arial,sans-serif" font-size="14">{escape(language)}</text>'
            f'<rect x="238" y="{y - 13}" width="500" height="9" rx="4.5" fill="#263244"/>'
            f'<rect x="238" y="{y - 13}" width="{500 * percentage / 100:.2f}" height="9" rx="4.5" fill="{color}"/>'
            f'<text x="824" y="{y}" text-anchor="end" fill="{TEXT}" font-family="Segoe UI,Arial,sans-serif" font-size="13" font-weight="600">{label}</text>'
        )

    height = max(190, 88 + len(rows) * 31 + 40)
    content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="880" height="{height}" viewBox="0 0 880 {height}" role="img" aria-labelledby="title description">
  <title id="title">GitHub-detected repository language distribution</title>
  <desc id="description">Language percentages by GitHub-detected source code bytes across {len(language_bytes)} languages in eligible owned public repositories. This is not a measure of personal skill.</desc>
  <rect width="880" height="{height}" rx="20" fill="{BACKGROUND}"/>
  <rect x="1" y="1" width="878" height="{height - 2}" rx="19" fill="none" stroke="#263244"/>
  <text x="32" y="42" fill="{GOLD}" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700" letter-spacing="2">LANGUAGES &amp; TECHNOLOGY ANALYTICS</text>
  <text x="32" y="68" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="12">Repository code-language distribution · GitHub-detected bytes · not skill proficiency</text>
  {''.join(rows)}
  <text x="832" y="{height - 14}" text-anchor="end" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">Updated {escape(timestamp)} · Forks and archived repositories excluded</text>
</svg>
"""
    (OUTPUT_DIR / "languages.svg").write_text(content, encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    repositories = get_repositories()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        language_sets = list(executor.map(get_language_bytes, repositories))

    totals: dict[str, int] = {}
    for language_set in language_sets:
        for language, amount in language_set.items():
            totals[language] = totals.get(language, 0) + amount

    generated = dt.datetime.now(dt.timezone.utc)
    write_stats_svg(repositories, generated)
    write_languages_svg(totals, generated)
    print(
        "Updated profile cards from "
        f"{len(repositories)} eligible owned public repositories "
        f"({len(totals)} detected languages; {CACHE_HITS} ETag cache hits)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Profile analytics update failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
