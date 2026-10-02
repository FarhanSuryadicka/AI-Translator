"""Membuat app/assets/icon.png + icon.ico (dijalankan sekali; hasilnya ikut disimpan di repo)."""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "app", "assets")
S = 1024
FONTS = r"C:\Windows\Fonts"


def font(names, size):
    for n in names:
        p = os.path.join(FONTS, n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def gradient(size, top, bottom):
    g = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return g.resize((size, size))


def bubble(draw, box, fill, tail_left):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=90, fill=fill)
    if tail_left:
        draw.polygon([(x0 + 70, y1 - 10), (x0 + 40, y1 + 110), (x0 + 210, y1 - 10)], fill=fill)
    else:
        draw.polygon([(x1 - 70, y1 - 10), (x1 - 40, y1 + 110), (x1 - 210, y1 - 10)], fill=fill)


def main():
    bg = gradient(S, (37, 99, 235), (13, 148, 136))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=220, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(img)
    bubble(d, (110, 150, 610, 560), (255, 255, 255, 255), tail_left=True)
    bubble(d, (420, 440, 920, 850), (15, 23, 42, 235), tail_left=False)
    latin = font(["segoeuib.ttf", "arialbd.ttf"], 330)
    cjk = font(["msyhbd.ttc", "msyh.ttc", "YuGothB.ttc", "msgothic.ttc"], 300)
    d.text((360, 355), "A", font=latin, fill=(37, 99, 235), anchor="mm")
    d.text((670, 645), "文", font=cjk, fill=(255, 255, 255), anchor="mm")

    os.makedirs(OUT, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    img.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("OK:", OUT)


if __name__ == "__main__":
    main()
