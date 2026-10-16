"""Ảnh màn hình chờ (splash) của AoE-MapCap.exe, kiểu XArena: nền than tối, ánh đỏ, viền vàng kim, logo + tên.
build.py gọi make_splash() rồi PyInstaller hiện ảnh này ngay khi mở exe (trong lúc giải nén), app đóng nó khi sẵn sàng."""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))


def _font(name, size):
    try:
        return ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", name), size)
    except OSError:
        return ImageFont.load_default()


def make_splash(out, w=520, h=260):
    bg = (22, 22, 27)
    im = Image.new("RGB", (w, h), bg)
    glow = Image.new("RGB", (w, h), bg)
    ImageDraw.Draw(glow).ellipse([w * 0.35, -h * 0.6, w * 1.15, h * 1.3], fill=(110, 10, 22))
    im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(60)), 0.6)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(192, 144, 88), width=1)
    d.rectangle([0, h - 4, w, h], fill=(192, 8, 32))
    try:
        logo = Image.open(os.path.join(ROOT, "assets", "app.ico")).convert("RGBA").resize((84, 84), Image.LANCZOS)
        im.paste(logo, (36, 72), logo)
    except OSError:
        pass
    d.text((140, 78), "AoE-MapCap", fill=(255, 255, 255), font=_font("Roboto-Bold.ttf", 36))
    d.text((142, 126), "Ghi trận và xem replay Age of Empires", fill=(200, 200, 210), font=_font("Roboto-Regular.ttf", 15))
    d.text((142, 166), "ĐANG KHỞI ĐỘNG…", fill=(226, 184, 120), font=_font("Roboto-Bold.ttf", 13))
    im.save(out)
    return out


if __name__ == "__main__":
    print(make_splash(os.path.join(ROOT, "build_assets", "splash.png")))
