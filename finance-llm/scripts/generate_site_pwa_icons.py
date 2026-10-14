"""Gera os ícones de PWA do site público (Sabemos Studio) em `api/site_assets/`.

Desenha a mesma marca do logótipo (`icone-sabemos-studio.svg`): um quadrado com
gradiente turquesa → azul e três barras brancas ascendentes.

O site não tem passo de "build" de frontend — é HTML gerado pelo backend — por
isso os PNG ficam versionados no repositório; quem os serve é a rota
`/site/pwa/<ficheiro>` (`api/cms_routes.py`), com caminho fixo (ao contrário dos
ids da biblioteca de media, que são aleatórios em cada instalação).

Uso:
    python scripts/generate_site_pwa_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SAIDA = Path(__file__).resolve().parents[1] / "api" / "site_assets"

SS = 4  # super-amostragem, para suavizar as bordas
GRADIENT_START = (14, 165, 164)   # turquesa (#0ea5a4)
GRADIENT_END = (29, 78, 216)      # azul (#1d4ed8)

# Lado de referência e geometria da marca, iguais aos do SVG.
LADO = 64.0
RAIO_QUADRADO = 0.25   # canto arredondado, em fração do lado (16/64)
RAIO_BARRA = 4.7       # em percentagem do lado (3/64)
BARRAS = ((15, 34, 8, 15), (28, 24, 8, 25), (41, 15, 8, 34))  # x, y, largura, altura


def gradient(size: int) -> Image.Image:
    """Gradiente diagonal turquesa → azul.

    O degradê do SVG é linear ao longo da diagonal, por isso basta interpolar os
    quatro cantos de um quadrado 2×2 — o `resize` faz a mesma conta para todos
    os píxeis, em vez de um ciclo em Python sobre milhões deles.
    """
    meio = tuple(round((inicio + fim) / 2) for inicio, fim in zip(GRADIENT_START, GRADIENT_END))
    cantos = Image.new("RGB", (2, 2))
    cantos.putpixel((0, 0), GRADIENT_START)
    cantos.putpixel((1, 1), GRADIENT_END)
    cantos.putpixel((1, 0), meio)
    cantos.putpixel((0, 1), meio)
    return cantos.resize((size, size), Image.BILINEAR)


def draw_mark(draw: ImageDraw.ImageDraw, size: int) -> None:
    """As três barras ascendentes, a branco (coordenadas do SVG, sobre 64)."""
    u = size / LADO
    for x, y, largura, altura in BARRAS:
        draw.rounded_rectangle(
            [x * u, y * u, (x + largura) * u, (y + altura) * u],
            radius=RAIO_BARRA / 100.0 * size,
            fill=(255, 255, 255, 255),
        )


def render(size: int, *, scale: float = 1.0, rounded: bool) -> Image.Image:
    """Ícone quadrado. `rounded` = cantos arredondados com fundo transparente."""
    big = size * SS
    canvas = gradient(big).convert("RGBA")

    mark = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw_mark(ImageDraw.Draw(mark), big)
    if scale != 1.0:
        side = int(big * scale)
        resized = mark.resize((side, side), Image.LANCZOS)
        mark = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        mark.alpha_composite(resized, ((big - side) // 2, (big - side) // 2))
    canvas.alpha_composite(mark)

    if rounded:
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, big - 1, big - 1], radius=int(big * RAIO_QUADRADO), fill=255
        )
        canvas.putalpha(mask)

    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)

    # Cantos arredondados com transparência (ecrã inicial e lojas).
    for nome, lado in (("pwa-icone-192.png", 192), ("pwa-icone-512.png", 512)):
        render(lado, rounded=True).save(SAIDA / nome)
        print(f"escrito {SAIDA / nome}")

    # `maskable`: fundo em sangria total e marca a 78% (zona segura de qualquer máscara).
    render(512, scale=0.78, rounded=False).convert("RGB").save(SAIDA / "pwa-icone-maskable-512.png")
    print(f"escrito {SAIDA / 'pwa-icone-maskable-512.png'}")

    # iOS (180): quadrado e sem transparência — o canto é arredondado pelo sistema.
    render(180, scale=0.78, rounded=False).convert("RGB").save(SAIDA / "pwa-icone-180.png")
    print(f"escrito {SAIDA / 'pwa-icone-180.png'}")


if __name__ == "__main__":
    main()
