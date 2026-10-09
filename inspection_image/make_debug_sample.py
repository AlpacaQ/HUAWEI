"""生成一张合成调试图，不是现场巡检照片。"""
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    output = Path(__file__).resolve().parent / "examples"
    output.mkdir(exist_ok=True)
    image = Image.new("RGB", (803, 607))
    image.putdata([(x * 255 // 802, y * 255 // 606, (x+y) % 256)
                   for y in range(607) for x in range(803)])
    draw = ImageDraw.Draw(image)
    draw.rectangle((450, 310, 719, 519), fill="white", outline="black", width=4)
    draw.text((480, 370), "DEBUG ONLY: 123.4", fill="black", font_size=24)
    draw.text((20, 20), "SYNTHETIC TEST IMAGE - NOT FIELD DATA", fill="white", font_size=20)
    image.save(output / "debug_sample.png")
    print(output / "debug_sample.png")


if __name__ == "__main__":
    main()
