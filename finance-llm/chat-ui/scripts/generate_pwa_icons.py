"""Gera os ícones do PWA (IQ OS) em `public/`.

Desenha uma marca simples e legível mesmo a 16 px — duas barras ascendentes e
um "spark" (dados + IA) sobre um gradiente teal → azul, igual ao badge da
plataforma.

Uso:
    python scripts/generate_pwa_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PUBLIC = Path(__file__).resolve().parent.parent / "public"

SS = 4  # super-amostragem, para suavizar as bordas
GRADIENT_START = (18, 184, 134)   # teal
GRADIENT_END = (37, 99, 235)      # azul


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


def sparkle_points(cx: float, cy: float, radius: float, waist: float = 0.26) -> list[tuple[float, float]]:
    """Spark de quatro pontas com arestas retas (igual ao ícone `Sparkles`)."""
    w = radius * waist
    return [
        (cx, cy - radius),
        (cx + w, cy - w),
        (cx + radius, cy),
        (cx + w, cy + w),
        (cx, cy + radius),
        (cx - w, cy + w),
        (cx - radius, cy),
        (cx - w, cy - w),
    ]


def draw_mark(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Marca: duas barras ascendentes + spark, a branco (coordenadas em %)."""
    u = size / 100.0

    def bar(x0: float, y0: float, x1: float, y1: float, fill) -> None:
        draw.rounded_rectangle([x0 * u, y0 * u, x1 * u, y1 * u], radius=4.6 * u, fill=fill)

    soft = (255, 255, 255, 205)
    white = (255, 255, 255, 255)
    bar(28, 58, 37.5, 74, soft)
    bar(41.5, 47, 51, 74, white)
    draw.polygon([(x * u, y * u) for x, y in sparkle_points(65, 37, 17)], fill=white)


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
