"""Testa a pesquisa web e a leitura de páginas da internet (coletores sociais)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import social_collectors as sc  # noqa: E402


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Wilson Mendes administrador judicial insolvencia Leiria"
    found = sc.search_web(query, limit=6)
    print("motor:", found.get("engine"), "| erro:", found.get("error"), "| itens:", len(found["items"]))
    for item in found["items"]:
        print(f"  - {item['title'][:80]} | {item['url']}")

    for item in found["items"][:3]:
        try:
            post = sc.collect_web_page(item["url"], tags=["teste"])
        except sc.CollectorError as exc:
            print(f"  ! {item['url'][:60]}: {exc.status} — {exc}")
            continue
        media = post.get("media") or {}
        print(f"  ✓ {post['title'][:70]}")
        print(f"      texto: {post['text'][:110]}")
        print(f"      imagem: {media.get('image', '')[:90]}")
        print(f"      video: {media.get('video', '')[:90]}")
        print("      data:", post.get("published_at"), "| site:", (post.get("data") or {}).get("site"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
