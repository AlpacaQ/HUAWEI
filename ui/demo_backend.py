"""石韵涵界面的独立接口测试后端，不是队友最终提交的图片或传输模块。

测试图由程序绘制，只是软件测试素材，不代表现场照片或正式实验数据。
计时模型仅为固定有效速率下的 JPEG 载荷顺序传输，不包含网络协议开销、
丢包、重传和传播时延，也不代表 5G 链路仿真。
"""

from __future__ import annotations

import json
import math
import time
from numbers import Integral
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """优先用常见字体；没有系统字体时使用 Pillow 自带字体。"""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def create_demo_image() -> Image.Image:
    """生成 960×640 RGB 几何仪表测试图；123.4 是虚构测试读数。"""
    image = Image.new("RGB", (960, 640), "#edf2f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 959, 78), fill="#17324d")
    draw.text((30, 16), "INTERFACE TEST / NOT FIELD DATA", fill="white", font=_font(33, True))
    draw.text((32, 98), "Synthetic inspection fixture - dummy reading", fill="#334a61", font=_font(24))

    # 几何设备外形用于观察分块恢复，避免让示例看起来像真实实验照片。
    draw.rounded_rectangle((55, 154, 498, 555), radius=20, fill="#ccd7e2", outline="#698197", width=4)
    draw.text((83, 179), "TEST CABINET", fill="#243d55", font=_font(30, True))
    for top in range(238, 493, 43):
        draw.rounded_rectangle((86, top, 467, top + 15), radius=6, fill="#899faf")
    draw.ellipse((390, 498, 420, 528), fill="#16a57e", outline="#0c6952", width=3)
    draw.text((82, 502), "Synthetic device", fill="#334a61", font=_font(23))
    draw.line((500, 271, 771, 271, 771, 337), fill="#6d879d", width=18)
    draw.ellipse((758, 253, 788, 283), fill="#aac0d0", outline="#567187", width=3)

    # 读数完整放在默认右下 ROI：约 [0.60W,0.55H,0.94W,0.88H] 内。
    draw.rounded_rectangle((581, 355, 897, 560), radius=15, fill="#263d51", outline="#6d879d", width=4)
    draw.text((602, 373), "DUMMY METER", fill="#d6e6f2", font=_font(23, True))
    draw.rounded_rectangle((599, 412, 879, 510), radius=8, fill="#d8eccf")
    draw.text((616, 417), "123.4", fill="#203b23", font=_font(75, True))
    draw.text((603, 526), "TEST VALUE ONLY", fill="#d6e6f2", font=_font(19))
    draw.text((31, 595), "Software fixture only. Do not use as competition evidence.", fill="#5a7083", font=_font(23))
    return image


def _roi_bounds(roi, width: int, height: int) -> tuple[int, int, int, int]:
    """坐标是整数像素，使用左上包含、右下不包含的半开区间。"""
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise ValueError("ROI 必须包含四个坐标：[x0, y0, x1, y1]。")
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in roi):
        raise ValueError("ROI 坐标必须是整数像素。")
    x0, y0, x1, y1 = map(int, roi)
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("ROI 必须具有非零面积，并完整位于处理后图片内部。")
    return x0, y0, x1, y1


def _tile_bounds(index: int, width: int, height: int) -> tuple[int, int, int, int]:
    """用整数分界线覆盖整个图像，奇数宽高也不会遗漏边缘。"""
    row, col = divmod(index, 4)
    return col * width // 4, row * height // 4, (col + 1) * width // 4, (row + 1) * height // 4


def _intersects(box, roi) -> bool:
    return max(box[0], roi[0]) < min(box[2], roi[2]) and max(box[1], roi[1]) < min(box[3], roi[3])


def prepare_image(image_path, roi, output_dir) -> str:
    """生成同一批 JPEG 和清单供 B、C 共用；返回清单的绝对路径。

    输出文件不会被静默覆盖。调用方应为每次处理选择新目录，或直接复用
    已完成的清单。processing_ms 是本机实测处理耗时，不是链路时间。
    """
    started = time.perf_counter()
    source_path = Path(image_path).resolve()
    with Image.open(source_path) as opened:
        normalized = ImageOps.exif_transpose(opened).convert("RGB")
        normalized.load()
    width, height = normalized.size
    if width < 4 or height < 4:
        raise ValueError("4×4 分块要求图片宽高至少为 4 像素。")
    bounds = _roi_bounds(roi, width, height)
    normalize_ms = (time.perf_counter() - started) * 1000

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    reserved = ["manifest.json", "thumbnail.jpg"] + [f"tile_{index:02d}.jpg" for index in range(16)]
    if any((output_path / name).exists() for name in reserved):
        raise FileExistsError("输出目录已有图片块或清单，请复用已有清单或选择新的输出目录。")

    crop_started = time.perf_counter()
    thumbnail = normalized.copy()
    thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)
    pieces = [(index, _tile_bounds(index, width, height)) for index in range(16)]
    tiles = [(index, box, normalized.crop(box)) for index, box in pieces]
    crop_ms = (time.perf_counter() - crop_started) * 1000

    encode_started = time.perf_counter()
    packets = []

    def save_packet(packet_id, pixels, box, priority, quality, filename):
        target = output_path / filename
        # 独占创建保证已有 JPEG 不会被覆盖。
        with target.open("xb") as stream:
            pixels.save(stream, format="JPEG", quality=quality)
        packets.append({
            "packet_id": packet_id,
            "bbox": list(box),
            "priority": priority,
            "quality": quality,
            "file": filename,
            "nbytes": target.stat().st_size,
        })

    save_packet("thumb", thumbnail, (0, 0, width, height), 0, 50, "thumbnail.jpg")
    for index, box, pixels in tiles:
        packet_id = f"tile_{index:02d}"
        save_packet(packet_id, pixels, box, 1 if _intersects(box, bounds) else 2, 80, f"{packet_id}.jpg")
    encode_ms = (time.perf_counter() - encode_started) * 1000

    manifest = {
        "image_id": source_path.stem,
        "width": width,
        "height": height,
        "roi": list(bounds),
        "packets": packets,
        "processing_ms": {
            "normalize_ms": normalize_ms,
            "crop_ms": crop_ms,
            "encode_ms": encode_ms,
            "total_ms": (time.perf_counter() - started) * 1000,
        },
        "processing_note": "本机实测；crop_ms 含缩略图缩放，encode_ms 含 JPEG 写盘；total_ms 不含清单写盘。",
        "backend_kind": "isolated_interface_test_backend",
    }
    manifest_path = output_path / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return str(manifest_path)


def _read_checked_manifest(manifest_path):
    """使用前检查清单结构、网格、优先级和真实文件大小。"""
    manifest_path = Path(manifest_path).resolve()
    with manifest_path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict):
        raise ValueError("图片清单必须是一个 JSON 对象。")
    width, height = manifest.get("width"), manifest.get("height")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 4 for value in (width, height)):
        raise ValueError("清单的图片宽高必须是至少为 4 的整数。")
    roi = _roi_bounds(manifest.get("roi"), width, height)
    packets = manifest.get("packets")
    if not isinstance(packets, list) or len(packets) != 17 or any(not isinstance(packet, dict) for packet in packets):
        raise ValueError("清单必须包含一个缩略图和十六个图片块。")
    packet_ids = [packet.get("packet_id") for packet in packets]
    expected_ids = {"thumb"} | {f"tile_{index:02d}" for index in range(16)}
    if any(not isinstance(packet_id, str) for packet_id in packet_ids) or set(packet_ids) != expected_ids:
        raise ValueError("图片块编号必须恰为 thumb 和 tile_00 至 tile_15，不能重复或缺失。")
    used_files = set()
    for packet in packets:
        packet_id = packet["packet_id"]
        if packet_id == "thumb":
            expected_box = (0, 0, width, height)
            expected_priority, expected_quality = 0, 50
        else:
            expected_box = _tile_bounds(int(packet_id[-2:]), width, height)
            expected_priority = 1 if _intersects(expected_box, roi) else 2
            expected_quality = 80
        if packet.get("bbox") != list(expected_box):
            raise ValueError(f"{packet_id} 的坐标与 4×4 分块规则不一致。")
        if packet.get("priority") != expected_priority or packet.get("quality") != expected_quality:
            raise ValueError(f"{packet_id} 的优先级或 JPEG 质量与第一版约定不一致。")
        filename = packet.get("file")
        if not isinstance(filename, str) or not filename or Path(filename).is_absolute():
            raise ValueError(f"{packet_id} 的文件路径必须是清单目录内的相对路径。")
        file_path = (manifest_path.parent / filename).resolve()
        if not file_path.is_relative_to(manifest_path.parent):
            raise ValueError(f"{packet_id} 的文件路径不能逃出清单目录。")
        if file_path in used_files:
            raise ValueError("每个图片块必须对应独立的文件。")
        used_files.add(file_path)
        nbytes = packet.get("nbytes")
        if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes <= 0:
            raise ValueError(f"{packet_id} 的 nbytes 必须是正整数。")
        if not file_path.is_file() or file_path.stat().st_size != nbytes:
            raise ValueError(f"{packet_id} 的文件不存在，或实际大小与清单不一致。")
    return manifest


def simulate(manifest_path, rate_mbps, mode) -> dict:
    """按实际 JPEG 字节数计算时间，不等待、不重编码、不修改任何文件。"""
    if mode not in ("B", "C"):
        raise ValueError("发送模式只能是 B（普通顺序）或 C（重点优先）。")
    if isinstance(rate_mbps, bool):
        raise ValueError("有效速率必须是有限的正数，单位 Mbps。")
    try:
        rate = float(rate_mbps)
    except (TypeError, ValueError):
        raise ValueError("有效速率必须是有限的正数，单位 Mbps。") from None
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(rate * 1_000_000):
        raise ValueError("有效速率必须是有限的正数，单位 Mbps。")
    manifest = _read_checked_manifest(manifest_path)
    if mode == "B":
        ordered = sorted(manifest["packets"], key=lambda packet: (packet["packet_id"] != "thumb", packet["packet_id"]))
    else:
        ordered = sorted(manifest["packets"], key=lambda packet: (packet["priority"], packet["packet_id"]))

    # 1 Mbps = 1,000,000 bit/s。累计字节数计算可确保两种顺序的总时间相同。
    bits_per_second = rate * 1_000_000
    cumulative_bytes = 0
    roi_complete_s = 0.0
    events = []
    for packet in ordered:
        start_s = cumulative_bytes * 8 / bits_per_second
        cumulative_bytes += packet["nbytes"]
        arrival_s = cumulative_bytes * 8 / bits_per_second
        if not math.isfinite(arrival_s):
            raise ValueError("有效速率过小，无法表示模拟到达时间。")
        events.append({
            "packet_id": packet["packet_id"],
            "start_s": start_s,
            "arrival_s": arrival_s,
            "cumulative_bytes": cumulative_bytes,
        })
        if packet["priority"] == 1:
            roi_complete_s = max(roi_complete_s, arrival_s)
    return {
        "events": events,
        "roi_complete_s": roi_complete_s,
        "full_complete_s": events[-1]["arrival_s"],
        "total_bytes": cumulative_bytes,
    }
