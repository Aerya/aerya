#!/usr/bin/env python3
"""
Met à jour la section blog du README.md avec les 3 derniers articles d'upandclear.org.
Utilise l'API WordPress REST pour récupérer titre, lien, date et image featured.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import requests

API_URL  = "https://upandclear.org/wp-json/wp/v2/posts"
README   = Path(__file__).parent / "README.md"
NB_POSTS = 3

MONTHS_FR = {
    1: "jan", 2: "fév", 3: "mar", 4: "avr",
    5: "mai", 6: "jun", 7: "juil", 8: "août",
    9: "sep", 10: "oct", 11: "nov", 12: "déc",
}


def fetch_posts() -> list[dict]:
    resp = requests.get(
        API_URL,
        params={
            "per_page": NB_POSTS,
            "_embed":   "wp:featuredmedia",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


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


def build_html(posts: list[dict]) -> str:
    cells = ""
    for post in posts:
        title = post["title"]["rendered"]
        link  = post["link"]
        date  = format_date(post["date"])
        img   = get_image(post)

        img_tag = (
            f'<img src="{img}" width="240" alt="{title}" /><br/>'
            if img else ""
        )
        cells += (
            f'    <td align="center" valign="top" width="33%">\n'
            f'      <a href="{link}">\n'
            f'        {img_tag}\n'
            f'        <b>{title}</b><br/>\n'
            f'        <sub>{date}</sub>\n'
            f'      </a>\n'
            f'    </td>\n'
        )

    return (
        '<table>\n'
        '  <tr>\n'
        f'{cells}'
        '  </tr>\n'
        '</table>'
    )


def update_readme(html: str) -> None:
    content = README.read_text(encoding="utf-8")
    new_block = f"<!-- BLOG:START -->\n{html}\n<!-- BLOG:END -->"
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
        html  = build_html(posts)
        update_readme(html)
    except requests.RequestException as e:
        print(f"Erreur API : {e}", file=sys.stderr)
        sys.exit(1)
