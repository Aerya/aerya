#!/usr/bin/env python3
"""
Met a jour la section des projets recents du README.md depuis les repos GitHub publics.

Les resumes sont conserves dans .github/repo_summaries.json. OpenRouter n'est appele
que lorsqu'un resume manque ou que la source du repo a change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).parent
README = ROOT / "README.md"
CACHE = ROOT / ".github" / "repo_summaries.json"

GITHUB_USER = os.getenv("GITHUB_USER", "Aerya")
NB_REPOS = int(os.getenv("NB_REPOS", "0"))
EXCLUDED_REPOS = {
    name.strip().lower()
    for name in os.getenv("EXCLUDED_REPOS", "aerya").split(",")
    if name.strip()
}

GITHUB_API = "https://api.github.com"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite")


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repos() -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/users/{GITHUB_USER}/repos",
            params={
                "per_page": 100,
                "page": page,
                "type": "owner",
                "sort": "pushed",
                "direction": "desc",
            },
            headers=github_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk:
            break
        repos.extend(chunk)
        page += 1

    filtered = [
        repo for repo in repos
        if not repo.get("private")
        and not repo.get("fork")
        and repo["name"].lower() not in EXCLUDED_REPOS
    ]
    sorted_repos = sorted(filtered, key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    return sorted_repos[:NB_REPOS] if NB_REPOS > 0 else sorted_repos


def fetch_readme_meta(repo: dict[str, Any]) -> tuple[str, str]:
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo['full_name']}/readme",
            headers=github_headers(),
            timeout=15,
        )
        if resp.status_code == 404:
            return "", ""
        resp.raise_for_status()
        data = resp.json()
        return data.get("sha") or "", data.get("download_url") or ""
    except requests.RequestException:
        return "", ""


def fetch_readme_text(download_url: str) -> str:
    if not download_url:
        return ""
    try:
        resp = requests.get(download_url, timeout=15)
        resp.raise_for_status()
        return resp.text[:6000]
    except requests.RequestException:
        return ""


def fingerprint(repo: dict[str, Any], readme_sha: str) -> str:
    source = {
        "name": repo.get("name") or "",
        "description": repo.get("description") or "",
        "homepage": repo.get("homepage") or "",
        "readme_sha": readme_sha,
    }
    raw = json.dumps(source, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache() -> dict[str, Any]:
    if not CACHE.exists():
        return {"version": 1, "repos": {}}
    return json.loads(CACHE.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, Any]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fallback_summary(repo: dict[str, Any]) -> str:
    description = (repo.get("description") or "").strip()
    if description:
        return description
    return "Projet public GitHub maintenu dans le cadre de mes outils et expérimentations personnelles."


def clean_summary(text: str) -> str:
    lines = [line.strip(" -") for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    summary = " ".join(lines)
    summary = re.sub(r"\s+", " ", summary)
    return summary[:420].rstrip(" ,;")


def summarize_with_openrouter(repo: dict[str, Any], readme_text: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return ""

    prompt = {
        "nom": repo.get("name"),
        "description": repo.get("description") or "",
        "langage": repo.get("language") or "",
        "homepage": repo.get("homepage") or "",
        "readme": readme_text,
    }
    resp = requests.post(
        OPENROUTER_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Aerya GitHub README updater",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Tu resumes des depots GitHub en francais. "
                        "Reponds avec un seul resume, maximum deux lignes, ton sobre et concret. "
                        "N'invente rien; si les informations sont faibles, reformule la description."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 120,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return clean_summary(content)


def get_summary(
    repo: dict[str, Any],
    cache: dict[str, Any],
    readme_sha: str,
    download_url: str,
) -> str:
    repo_cache = cache.setdefault("repos", {})
    key = repo["full_name"]
    fp = fingerprint(repo, readme_sha)
    entry = repo_cache.get(key, {})

    if entry.get("summary") and entry.get("source") == "manual":
        entry["fingerprint"] = fp
        entry["updated_at"] = now()
        repo_cache[key] = entry
        return entry["summary"]

    if entry.get("summary") and entry.get("fingerprint") == fp:
        return entry["summary"]

    if entry.get("summary") and not entry.get("fingerprint"):
        entry["fingerprint"] = fp
        entry["updated_at"] = now()
        repo_cache[key] = entry
        return entry["summary"]

    readme_text = fetch_readme_text(download_url)
    try:
        summary = summarize_with_openrouter(repo, readme_text)
        source = "openrouter" if summary else "github-description"
    except requests.RequestException as exc:
        print(f"OpenRouter indisponible pour {key}: {exc}", file=sys.stderr)
        summary = ""
        source = "github-description"

    if not summary:
        summary = fallback_summary(repo)

    repo_cache[key] = {
        "fingerprint": fp,
        "summary": clean_summary(summary),
        "source": source,
        "updated_at": now(),
    }
    return repo_cache[key]["summary"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_repo_list(lines: list[str], repos: list[dict[str, Any]], cache: dict[str, Any]) -> None:
    for repo in repos:
        readme_sha, download_url = fetch_readme_meta(repo)
        summary = get_summary(repo, cache, readme_sha, download_url)
        lines.extend([
            f"- [**{repo['name']}**]({repo['html_url']})",
            f"  {summary}",
            "",
        ])


def build_markdown(repos: list[dict[str, Any]], cache: dict[str, Any]) -> str:
    recent_repos = repos[:5]
    other_repos = repos[5:]

    lines = ["### Derniers repos", ""]
    append_repo_list(lines, recent_repos, cache)

    lines.extend([
        "---",
        "",
        "### Stats GitHub",
        "",
        '<p align="center">',
        '  <img src="https://github-readme-stats.vercel.app/api?username=Aerya&show_icons=false&hide_border=true&theme=transparent&locale=fr" alt="Statistiques GitHub" />',
        '  <img src="https://github-readme-stats.vercel.app/api/top-langs/?username=Aerya&layout=compact&hide_border=true&theme=transparent&locale=fr" alt="Langages les plus utilisés" />',
        "</p>",
        "",
        "---",
        "",
        "### Autres repos",
        "",
    ])
    append_repo_list(lines, other_repos, cache)

    return "\n".join(lines).rstrip()


def update_readme(markdown: str) -> None:
    content = README.read_text(encoding="utf-8")
    block = f"<!-- REPOS:START -->\n{markdown}\n<!-- REPOS:END -->"

    if "<!-- REPOS:START -->" in content:
        updated = re.sub(
            r"<!-- REPOS:START -->.*?<!-- REPOS:END -->",
            block,
            content,
            flags=re.DOTALL,
        )
    else:
        updated = re.sub(
            r"(<!-- BLOG:END -->).*",
            "\\1\n\n---\n\n" + block + "\n",
            content,
            flags=re.DOTALL,
        )

    if updated == content:
        print("Aucun changement detecte dans les projets.")
        return
    README.write_text(updated, encoding="utf-8")
    print("README.md mis a jour avec les projets recents.")


def main() -> None:
    cache = load_cache()
    repos = fetch_repos()
    markdown = build_markdown(repos, cache)
    update_readme(markdown)
    save_cache(cache)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        print(f"Erreur API: {exc}", file=sys.stderr)
        sys.exit(1)
