"""Draw the toolbar icons (a cookie with a bite taken out and a tick).
Requires Pillow; the PNGs are committed so building does not."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "extension" / "src" / "icons"


def draw(size: int) -> Image.Image:
    s = 8  # supersample
    W = size * s
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = int(W * 0.06)
    d.ellipse([pad, pad, W - pad, W - pad], fill=(196, 137, 70, 255))
    bite_r = int(W * 0.2)
    bx, by = int(W * 0.86), int(W * 0.16)
    d.ellipse([bx - bite_r, by - bite_r, bx + bite_r, by + bite_r], fill=(0, 0, 0, 0))
    for fx, fy, fr in ((0.32, 0.34, 0.07), (0.58, 0.55, 0.06), (0.36, 0.68, 0.055), (0.66, 0.32, 0.045)):
        r = int(W * fr)
        cx, cy = int(W * fx), int(W * fy)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(84, 52, 26, 255))
    if size >= 32:
        w = max(int(W * 0.09), 1)
        d.line([(int(W * 0.30), int(W * 0.56)), (int(W * 0.45), int(W * 0.72)), (int(W * 0.74), int(W * 0.40))], fill=(255, 255, 255, 255), width=w, joint="curve")
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for n in (16, 32, 48, 128):
        draw(n).save(OUT / f"{n}.png", optimize=True)
    print("icons written to", OUT)
