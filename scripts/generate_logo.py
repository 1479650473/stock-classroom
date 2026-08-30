"""Generate stock-classroom logo and Tauri icon set from scratch using Pillow.

Outputs:
  web/public/logo.svg          (placeholder kept as-is)
  _build/logo_512.png          (source PNG)
  _build/logo.ico              (ICO with multiple sizes)
  web/src-tauri/icons/         (Tauri v2 required icons)
    32x32.png
    128x128.png
    128x128@2x.png
    icon.icns                  (copy as .png for Linux)
    icon.ico
    icon.png

Design: dark rounded-rect background + gold "S" + subtle chart sparkline.
"""
from pathlib import Path
import math, struct

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("pip install Pillow"); raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "_build"
BUILD.mkdir(exist_ok=True)
ICONS_DIR = ROOT / "web" / "src-tauri" / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

# ---------- palette ----------
BG      = (20, 22, 28)       # #14161C
GOLD    = (212, 165, 116)    # #D4A574
GOLD2   = (180, 140, 95)     # darker accent
SPARK   = (100, 200, 130)    # green sparkline
RED     = (232, 64, 64)      # up candle
WHITE   = (255, 255, 255)

SIZES = [32, 48, 64, 128, 256, 512]

def draw_logo(size: int) -> Image.Image:
    """Render the logo at *size* x *size* pixels."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = size * 0.18  # corner radius

    # rounded-rect background
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    # --- letter "S" ---
    letter_h = size * 0.48
    letter_y = size * 0.22
    cx = size / 2

    # Try to load a bold font; fall back to default
    font = None
    for fp in [
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, int(letter_h))
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "S", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw / 2
    ty = letter_y - bbox[1]
    draw.text((tx, ty), "S", fill=GOLD, font=font)

    # --- sparkline below the letter ---
    sp_y0 = size * 0.68
    sp_h = size * 0.14
    sp_w = size * 0.52
    sp_x0 = cx - sp_w / 2
    n_pts = 12
    pts = []
    for i in range(n_pts):
        x = sp_x0 + (sp_w * i / (n_pts - 1))
        v = math.sin(i * 0.9 + 0.5) * 0.4 + math.cos(i * 0.4) * 0.3
        y = sp_y0 + sp_h * (0.5 - v)
        pts.append((x, y))

    line_w = max(1, int(size * 0.025))
    for i in range(len(pts) - 1):
        color = SPARK if pts[i + 1][1] <= pts[i][1] else RED
        draw.line([pts[i], pts[i + 1]], fill=color, width=line_w)

    # small dot at end
    ex, ey = pts[-1]
    dot_r = max(1, int(size * 0.02))
    draw.ellipse([ex - dot_r, ey - dot_r, ex + dot_r, ey + dot_r], fill=SPARK)

    return img


def main():
    imgs = {}
    for s in SIZES:
        im = draw_logo(s)
        imgs[s] = im
        im.save(BUILD / f"logo_{s}.png")
        print(f"  logo_{s}.png")

    # ICO (Windows) — embed 16,32,48,256
    ico_sizes = [16, 32, 48, 256]
    ico_imgs = []
    for s in ico_sizes:
        if s in imgs:
            ico_imgs.append(imgs[s].resize((s, s), Image.LANCZOS))
        else:
            ico_imgs.append(draw_logo(s))
    ico_path = BUILD / "logo.ico"
    ico_imgs[0].save(ico_path, format="ICO", sizes=[(s, s) for s in ico_sizes],
                     append_images=ico_imgs[1:])
    print(f"  logo.ico")

    # copy 512 PNG for Tauri icon.png
    imgs[512].save(ICONS_DIR / "icon.png")
    imgs[128].save(ICONS_DIR / "128x128.png")
    imgs[256].save(ICONS_DIR / "128x128@2x.png")
    imgs[32].save(ICONS_DIR / "32x32.png")
    ico_path.rename(ICONS_DIR / "icon.ico")
    print(f"  Tauri icons written to {ICONS_DIR}")

    print("Done.")


if __name__ == "__main__":
    main()
