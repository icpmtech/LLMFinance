"""Gera os ícones do PWA (IQ OS) em `public/`.

Desenha a marca **Sabemos Studio** — três barras ascendentes sobre o gradiente
teal → azul da marca — legível mesmo a 16 px. A geometria e as cores são as do
`api/site_assets/icone-sabemos-studio.svg`, que é o favicon vectorial: os dois
têm de dizer o mesmo, ou a aplicação e o site mostram marcas diferentes (foi o
que aconteceu, com um raio roxo na aba do browser).

Uso:
    python scripts/generate_pwa_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PUBLIC = Path(__file__).resolve().parent.parent / "public"

SS = 4  # super-amostragem, para suavizar as bordas
# As cores do SVG da marca (`#0ea5a4` → `#1d4ed8`), e não uma aproximação.
GRADIENT_START = (14, 165, 164)  # #0ea5a4
GRADIENT_END = (29, 78, 216)  # #1d4ed8


def gradient(size: int) -> Image.Image:
    """Gradiente diagonal teal → azul."""
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    span = 2 * (size - 1)
    for y in range(size):
        for x in range(size):
            t = (x + y) / span
            pixels[x, y] = (
                round(GRADIENT_START[0] + (GRADIENT_END[0] - GRADIENT_START[0]) * t),
                round(GRADIENT_START[1] + (GRADIENT_END[1] - GRADIENT_START[1]) * t),
                round(GRADIENT_START[2] + (GRADIENT_END[2] - GRADIENT_START[2]) * t),
            )
    return image


def draw_mark(draw: ImageDraw.ImageDraw, size: int) -> None:
    """As três barras da marca, a branco (coordenadas em % do lado).

    Os números são o SVG da marca (num `viewBox` de 64) dividido por 64: as
    barras acabam todas na mesma linha de base (49/64 = 76,6%) e crescem para a
    esquerda, como no ícone.
    """
    u = size / 100.0
    branco = (255, 255, 255, 255)

    def barra(x0: float, y0: float, x1: float, y1: float) -> None:
        draw.rounded_rectangle([x0 * u, y0 * u, x1 * u, y1 * u], radius=4.7 * u, fill=branco)

    barra(23.4, 53.1, 35.9, 76.6)
    barra(43.8, 37.5, 56.3, 76.6)
    barra(64.1, 23.4, 76.6, 76.6)


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
        radius = int(big * 0.22)
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=radius, fill=255)
        canvas.putalpha(mask)

    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # Cantos arredondados com transparência (ecrãs e atalhos).
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512)):
        render(size, rounded=True).save(PUBLIC / name)
        print(f"escrito {PUBLIC / name}")

    # `maskable`: fundo em sangria total e marca a 78% (zona segura de qualquer máscara).
    render(512, scale=0.78, rounded=False).convert("RGB").save(PUBLIC / "icon-maskable-512.png")
    print(f"escrito {PUBLIC / 'icon-maskable-512.png'}")

    # iOS (180) e favicon raster de recurso (32): quadrado, sem transparência.
    render(180, scale=0.78, rounded=False).convert("RGB").save(PUBLIC / "apple-touch-icon.png")
    render(32, rounded=False).convert("RGB").save(PUBLIC / "favicon-32.png")
    print("escritos apple-touch-icon.png e favicon-32.png")


if __name__ == "__main__":
    main()
