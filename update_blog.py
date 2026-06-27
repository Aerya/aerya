#!/usr/bin/env python3
"""
Met à jour la section blog du README.md avec les derniers articles d'upandclear.org.
Utilise l'API WordPress REST pour récupérer titre, lien, date et image featured.
"""

import html
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

API_URL = "https://upandclear.org/wp-json/wp/v2/posts"
README = Path(__file__).parent / "README.md"
NB_POSTS = 4
LATEST_IMAGE_WIDTH = 72
RANDOM_IMAGE_WIDTH = 120

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def build_session() -> requests.Session:
    """Session partagée. Le header X-Blog-Sync (secret) permet de contourner
    la règle Cloudflare qui bloque les IP des runners GitHub Actions."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    sync_token = os.environ.get("BLOG_SYNC_TOKEN")
    if sync_token:
        session.headers["X-Blog-Sync"] = sync_token
    return session


SESSION = build_session()

MONTHS_FR = {
    1: "jan", 2: "fév", 3: "mar", 4: "avr",
    5: "mai", 6: "jun", 7: "juil", 8: "août",
    9: "sep", 10: "oct", 11: "nov", 12: "déc",
}


def fetch_posts() -> list[dict]:
    resp = SESSION.get(
        API_URL,
        params={
            "per_page": NB_POSTS,
            "_embed": "wp:featuredmedia",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_random_post(excluded_ids: set[int]) -> dict | None:
    count_resp = SESSION.get(
        API_URL,
        params={"per_page": 1},
        timeout=15,
    )
    count_resp.raise_for_status()
    total = int(count_resp.headers.get("X-WP-Total", "0"))
    if total <= NB_POSTS:
        return None

    for _ in range(8):
        page = random.randint(1, total)
        resp = SESSION.get(
            API_URL,
            params={
                "per_page": 1,
                "page": page,
                "_embed": "wp:featuredmedia",
            },
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json()
        if posts and posts[0].get("id") not in excluded_ids:
            return posts[0]
    return None


def get_image(post: dict) -> str:
    """Retourne l'URL de l'image featured (taille medium si dispo, sinon full)."""
    try:
        media = post["_embedded"]["wp:featuredmedia"][0]
        sizes = media["media_details"]["sizes"]
        for size in ("medium", "medium_large", "thumbnail", "full"):
            if size in sizes:
                return sizes[size]["source_url"]
        return media["source_url"]
    except (KeyError, IndexError, TypeError):
        return ""


def format_date(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return f"{dt.day} {MONTHS_FR[dt.month]} {dt.year}"


def format_latest_post(post: dict) -> str:
    title = html.unescape(post["title"]["rendered"])
    title_attr = html.escape(title, quote=True)
    link = post["link"]
    date = format_date(post["date"])
    img = get_image(post)
    img_tag = (
        f'<a href="{link}"><img align="left" src="{img}" width="{LATEST_IMAGE_WIDTH}" alt="{title_attr}" /></a>'
        if img else ""
    )
    return (
        '<p>\n'
        f'  {img_tag}\n'
        f'  <a href="{link}"><b>{html.escape(title)}</b></a><br/>\n'
        f'  <sub>{date}</sub>\n'
        '</p>\n'
        '<br clear="left"/>'
    )


def format_random_post(post: dict) -> str:
    title = html.unescape(post["title"]["rendered"])
    title_attr = html.escape(title, quote=True)
    link = post["link"]
    date = format_date(post["date"])
    img = get_image(post)
    img_tag = (
        f'<a href="{link}"><img align="left" src="{img}" width="{RANDOM_IMAGE_WIDTH}" alt="{title_attr}" /></a>'
        if img else ""
    )
    return (
        '<p>\n'
        f'  {img_tag}\n'
        f'  <a href="{link}"><b>{html.escape(title)}</b></a><br/>\n'
        f'  <sub>{date}</sub>\n'
        '</p>\n'
        '<br clear="left"/>'
    )


def build_html(posts: list[dict], random_post: dict | None) -> str:
    lines = ["#### Les derniers", ""]
    for post in posts:
        lines.append(format_latest_post(post))
        lines.append("")

    if random_post:
        lines.extend([
            "",
            "#### Au hasard du blog",
            "",
            format_random_post(random_post),
        ])

    return "\n".join(lines)


def update_readme(html_block: str) -> None:
    content = README.read_text(encoding="utf-8")
    new_block = f"<!-- BLOG:START -->\n{html_block}\n<!-- BLOG:END -->"
    updated = re.sub(
        r"<!-- BLOG:START -->.*?<!-- BLOG:END -->",
        new_block,
        content,
        flags=re.DOTALL,
    )
    if updated == content:
        print("Aucun changement détecté.")
        return
    README.write_text(updated, encoding="utf-8")
    print("README.md mis à jour avec les derniers articles.")


if __name__ == "__main__":
    try:
        posts = fetch_posts()
        random_post = fetch_random_post({post["id"] for post in posts})
        html_block = build_html(posts, random_post)
        update_readme(html_block)
    except requests.RequestException as e:
        print(f"Erreur API : {e}", file=sys.stderr)
        resp = getattr(e, "response", None)
        if resp is not None:
            for h in ("Server", "CF-Ray", "cf-mitigated", "CF-Cache-Status"):
                if h in resp.headers:
                    print(f"  {h}: {resp.headers[h]}", file=sys.stderr)
            print(f"  X-Blog-Sync envoyé: {'X-Blog-Sync' in SESSION.headers}", file=sys.stderr)
            print(f"  Corps (500c) : {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)
