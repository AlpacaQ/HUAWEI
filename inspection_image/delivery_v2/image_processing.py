"""第一版图像模块：只生成一批文件，不执行传输或保存设备ROI预设。"""
import argparse
import json
from numbers import Integral
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageOps

GRID_SIZE = 4
TILE_QUALITY = 80
THUMBNAIL_QUALITY = 50
THUMBNAIL_MAX_EDGE = 256


def load_processed_image(image_path):
    """先应用EXIF朝向，再转RGB；后续尺寸和ROI均基于这个结果。"""
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.load()
    # 输出不携带原来的EXIF朝向，避免接收端再次旋转。
    image.info.clear()
    return image


def validate_roi(roi, width, height):
    """验证整数像素坐标，不自动交换、截断或缩放用户选区。"""
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise ValueError("ROI必须为4个整数：[x0, y0, x1, y1]")
    if any(isinstance(v, bool) or not isinstance(v, Integral) for v in roi):
        raise ValueError("ROI坐标必须为整数，不接受小数或布尔值")
    x0, y0, x1, y1 = map(int, roi)
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"ROI无效，处理后图片为{width}×{height}；要求0≤x0<x1≤宽，0≤y0<y1≤高")
    return [x0, y0, x1, y1]


def tile_boxes(width, height):
    """用共享边界覆盖全部像素；编号0到15，先行后列。"""
    if width < GRID_SIZE or height < GRID_SIZE:
        raise ValueError("4×4 JPEG分块要求图片宽、高均至少为4像素")
    xs = [i * width // GRID_SIZE for i in range(GRID_SIZE + 1)]
    ys = [i * height // GRID_SIZE for i in range(GRID_SIZE + 1)]
    return [[xs[col], ys[row], xs[col + 1], ys[row + 1]]
            for row in range(GRID_SIZE) for col in range(GRID_SIZE)]


def intersects(box, roi):
    """严格面积相交：仅边界接触不会标为重点块。"""
    return (max(box[0], roi[0]) < min(box[2], roi[2])
            and max(box[1], roi[1]) < min(box[3], roi[3]))


def prepare_image(image_path, roi, output_dir):
    """生成thumbnail.jpg、16个JPEG及manifest.json，返回清单绝对路径字符串。

    output_dir必须为空或不存在，避免覆盖另一张图片或留下旧清单。
    payload是相对于清单目录的文件名；priority为1表示重点、0表示背景。
    """
    started = perf_counter()
    image = load_processed_image(image_path)
    width, height = image.size
    roi = validate_roi(roi, width, height)
    boxes = tile_boxes(width, height)
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output_dir必须为空目录或尚不存在的目录，请换一个输出目录")
    output.mkdir(parents=True, exist_ok=True)
    image_id = output.name

    # 缩略图只编码一次，保持比例；小图不会被放大。
    thumbnail = image.copy()
    thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
    thumb_path = output / "thumbnail.jpg"
    thumbnail.save(thumb_path, format="JPEG", quality=THUMBNAIL_QUALITY)
    thumb_record = {"image_id": image_id, "payload": thumb_path.name,
                    "size_bytes": thumb_path.stat().st_size,
                    "width": thumbnail.width, "height": thumbnail.height,
                    "quality": THUMBNAIL_QUALITY}

    # crop接受半开区间；每块仅在此处JPEG编码一次。
    tiles = []
    for tile_id, box in enumerate(boxes):
        x0, y0, x1, y1 = box
        path = output / f"tile_{tile_id:02d}.jpg"
        image.crop(tuple(box)).save(path, format="JPEG", quality=TILE_QUALITY)
        tiles.append({"image_id": image_id, "tile_id": tile_id,
                      "box": box, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                      "priority": int(intersects(box, roi)), "quality": TILE_QUALITY,
                      "payload": path.name, "size_bytes": path.stat().st_size})

    manifest = {"schema_version": 1, "image_id": image_id,
                "source_name": Path(image_path).name,
                "width": width, "height": height, "mode": "RGB", "roi": roi,
                "coordinate_convention": "[x0,y0,x1,y1), top-left inclusive, bottom-right exclusive",
                "grid": {"rows": GRID_SIZE, "cols": GRID_SIZE},
                "thumbnail": thumb_record, "tiles": tiles,
                "total_size_bytes": thumb_record["size_bytes"] + sum(t["size_bytes"] for t in tiles)}
    # 计时含读取、朝向转换、裁剪、编码、文件写入和实际长度读取。
    # 不含下面的清单序列化/落盘，不含人工检查、传输模拟和界面等待。
    manifest["image_processing_seconds"] = perf_counter() - started
    manifest["processing_time_scope"] = "image read through JPEG writes and file size reads; excludes manifest write"
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(manifest_path)


def main():
    parser = argparse.ArgumentParser(description="4×4图片分块（ROI基于EXIF校正后的RGB图片）")
    parser.add_argument("image_path")
    parser.add_argument("--roi", nargs=4, type=int, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        print(prepare_image(args.image_path, args.roi, args.output_dir))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"图片处理失败：{exc}\n")


if __name__ == "__main__":
    main()
