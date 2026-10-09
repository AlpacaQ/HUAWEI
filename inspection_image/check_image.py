"""人工检查及编码前像素验收；不会重新编码传输JPEG。"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from image_processing import load_processed_image, tile_boxes, validate_roi, intersects


def export_processed(image_path, output_path):
    """先导出朝向校正后的无损RGB图片，供选取ROI。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = load_processed_image(image_path)
    image.save(path, format="PNG")
    print(f"处理后尺寸：{image.width}×{image.height}，模式：{image.mode}；选区依据：{path.resolve()}")


def check_image(image_path, manifest_path, output_dir):
    image = load_processed_image(image_path)
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest["width"], manifest["height"]) != image.size or manifest["mode"] != "RGB":
        raise ValueError("清单尺寸/模式与处理后原图不一致")
    roi = validate_roi(manifest["roi"], *image.size)
    boxes = tile_boxes(*image.size)
    tiles = manifest["tiles"]
    if len(tiles) != 16:
        raise ValueError("清单必须包含16块")
    before = Image.new("RGB", image.size)
    after = Image.new("RGB", image.size)
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    encoded_total = 0

    for tile_id, (tile, box) in enumerate(zip(tiles, boxes)):
        x0, y0, x1, y1 = box
        if (tile["tile_id"] != tile_id or tile["box"] != box
                or [tile["x"], tile["y"], tile["w"], tile["h"]] != [x0, y0, x1-x0, y1-y0]
                or tile["priority"] != int(intersects(box, roi))):
            raise ValueError(f"第{tile_id}块编号、坐标或重点标记不符合约定")
        # 无损验收：直接裁剪内存中的RGB原图，再粘回同一位置。
        before.paste(image.crop(tuple(box)), (x0, y0))
        tile_path = manifest_path.parent / tile["payload"]
        if tile_path.stat().st_size != tile["size_bytes"]:
            raise ValueError(f"第{tile_id}块文件长度与清单不符")
        encoded_total += tile["size_bytes"]
        # JPEG仅解码；拼接结果保存为PNG，不增加一次JPEG损失。
        with Image.open(tile_path) as decoded:
            if decoded.size != (x1-x0, y1-y0) or decoded.mode != "RGB":
                raise ValueError(f"第{tile_id}块尺寸或颜色模式错误")
            after.paste(decoded, (x0, y0))
        color = "red" if tile["priority"] else "cyan"
        draw.rectangle((x0, y0, x1-1, y1-1), outline=color, width=2)
        draw.text((x0+3, y0+3), f"{tile_id:02d}" + (" ROI" if tile["priority"] else ""), fill=color, stroke_width=1, stroke_fill="black")

    thumb = manifest["thumbnail"]
    if (manifest_path.parent / thumb["payload"]).stat().st_size != thumb["size_bytes"]:
        raise ValueError("缩略图文件长度与清单不符")
    if encoded_total + thumb["size_bytes"] != manifest["total_size_bytes"]:
        raise ValueError("总字节数与17个JPEG文件不符")
    pixel_equal = ImageChops.difference(image, before).getbbox() is None
    if not pixel_equal:
        raise AssertionError("编码前裁剪并拼接未能恢复原图像素")
    x0, y0, x1, y1 = roi
    draw.rectangle((x0, y0, x1-1, y1-1), outline="yellow", width=3)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / "processed.png")
    annotated.save(output / "roi_tiles.png")
    before.save(output / "reassembled_before_encoding.png")
    after.save(output / "reassembled_after_jpeg.png")
    report = {"pre_encoding_pixel_equal": pixel_equal,
              "jpeg_pixel_equal": ImageChops.difference(image, after).getbbox() is None,
              "total_size_bytes": manifest["total_size_bytes"],
              "image_processing_seconds": manifest["image_processing_seconds"],
              "note": "JPEG像素差异属于有损编码，不作为裁剪错误判据；检查图片和PNG不计入传输字节数"}
    (output / "check_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"人工检查图片：{output}")
    return report


def main():
    parser = argparse.ArgumentParser(description="导出处理后图片或检查已有清单，不重新编码JPEG")
    parser.add_argument("image_path")
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir", default="check_output")
    parser.add_argument("--export-processed", metavar="PNG_PATH")
    args = parser.parse_args()
    if bool(args.manifest) == bool(args.export_processed):
        parser.error("请二选一：--manifest 或 --export-processed")
    try:
        if args.export_processed:
            export_processed(args.image_path, args.export_processed)
        else:
            check_image(args.image_path, args.manifest, args.output_dir)
    except (ValueError, OSError, KeyError, AssertionError) as exc:
        parser.exit(1, f"检查失败：{exc}\n")


if __name__ == "__main__":
    main()
