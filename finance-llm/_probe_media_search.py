"""Testa a pesquisa de imagens e vídeos (e a leitura de media das páginas)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import social_collectors as sc  # noqa: E402

QUERIES = [
    "Wilson Mendes administrador judicial",
    "Deolinda Ribas da Silva Albuquerque",
    "administrador de insolvencia Portugal entrevista",
    "insolvência empresas Portugal 2026",
]


def main() -> int:
    for query in QUERIES:
        videos = sc.search_videos(query, limit=5)
        images = sc.search_images(query, limit=6)
        print(f"== {query}")
        print(f"   vídeos: {len(videos.get('items') or [])} (erro: {videos.get('error')})")
        for item in (videos.get("items") or [])[:3]:
            print(f"      - {str(item.get('title'))[:55]} | {str(item.get('url'))[:60]} | thumb: {bool(item.get('thumbnail'))}")
        print(f"   imagens: {len(images.get('items') or [])} (erro: {images.get('error')})")
        for item in (images.get("items") or [])[:3]:
            print(f"      - {str(item.get('title'))[:45]} | {str(item.get('image'))[:70]}")

    # Leitura de uma página rica em media (deve trazer várias imagens e vídeos).
    for url in ("https://www.publico.pt/", "https://pt.wikipedia.org/wiki/Insolv%C3%AAncia"):
        try:
            post = sc.collect_web_page(url, tags=["teste-media"])
        except sc.CollectorError as exc:
            print(f"!! {url}: {exc.status} — {exc}")
            continue
        media = post.get("media") or {}
        print(f"== {url}: {len(media.get('images') or [])} imagem(ns), {len(media.get('videos') or [])} vídeo(s)")
        for image in (media.get("images") or [])[:4]:
            print("   img:", image[:95])
        for video in (media.get("videos") or [])[:4]:
            print("   vid:", video[:95])
    return 0


if __name__ == "__main__":
    sys.exit(main())
