#!/usr/bin/env python3
"""
Met à jour la section blog du README.md avec les derniers articles d'upandclear.org.
Utilise l'API WordPress REST pour récupérer titre, lien, date et image featured.
"""

import html
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

API_URL = "https://upandclear.org/wp-json/wp/v2/posts"
README = Path(__file__).parent / "README.md"
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
            "_embed": "wp:featuredmedia",
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
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
    rows = []
    for row_start in range(0, len(posts), 3):
        cells = ""
        for post in posts[row_start:row_start + 3]:
            title = html.unescape(post["title"]["rendered"])
            title_attr = html.escape(title, quote=True)
            link = post["link"]
            date = format_date(post["date"])
            img = get_image(post)

            img_tag = (
                f'<img src="{img}" width="240" alt="{title_attr}" /><br/>'
                if img else ""
            )
            cells += (
                f'    <td align="center" valign="top" width="33%">\n'
                f'      <a href="{link}">\n'
                f'        {img_tag}\n'
                f'        <b>{html.escape(title)}</b><br/>\n'
                f'        <sub>{date}</sub>\n'
                f'      </a>\n'
                f'    </td>\n'
            )
        rows.append(f"  <tr>\n{cells}  </tr>")

    return '<table>\n' + "\n".join(rows) + '\n</table>'


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
        html_block = build_html(posts)
        update_readme(html_block)
    except requests.RequestException as e:
        print(f"Erreur API : {e}", file=sys.stderr)
        sys.exit(1)
