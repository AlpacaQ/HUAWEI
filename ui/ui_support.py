"""界面的辅助函数：图片预览、设备预设、接收画面和日志导出。

这里只使用 Pillow 和 Python 标准库。传输顺序与到达时间由外部模块计算，
本文件不会提前打开未到达的 JPEG，也不会读取原始巡检照片来拼接接收画面。
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time

from PIL import Image, ImageDraw, ImageOps
from team_bridge import load_ui_manifest


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name}必须是正整数。")
    return value


def _roi_checked(roi, width, height):
    """坐标采用半开区间：[左, 上, 右, 下]。"""
    _positive_int(width, "图片宽度")
    _positive_int(height, "图片高度")
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise ValueError("ROI必须包含4个整数：[左, 上, 右, 下]。")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in roi):
        raise ValueError("ROI坐标必须是整数。")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("ROI坐标越界或区域为空，请检查图片尺寸和坐标。")
    return x0, y0, x1, y1


def load_normalized_image(image_bytes) -> Image.Image:
    """按手机照片的EXIF方向转正，并返回独立的RGB图片。"""
    with Image.open(io.BytesIO(image_bytes)) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def draw_roi_preview(image, roi) -> Image.Image:
    """在副本上画4×4网格和红色ROI；原图不会被修改。"""
    width, height = image.size
    x0, y0, x1, y1 = _roi_checked(roi, width, height)
    preview = image.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)
    line_width = max(1, min(width, height) // 250)
    for index in range(1, 4):
        x = index * width // 4
        y = index * height // 4
        draw.line((x, 0, x, height - 1), fill="yellow", width=line_width)
        draw.line((0, y, width - 1, y), fill="yellow", width=line_width)
    # 每个格子的标签同时给出编号和左上角坐标。
    for row in range(4):
        for col in range(4):
            x, y = col * width // 4, row * height // 4
            label = f"{row * 4 + col:02d} ({x},{y})"
            draw.text((x + 2, y + 2), label, fill="white", stroke_width=1,
                      stroke_fill="black")
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="red",
                   width=max(2, line_width * 2))
    label = f"ROI [{x0},{y0},{x1},{y1}]"
    draw.text((x0 + 2, max(0, y0 - 14)), label, fill="red",
              stroke_width=1, stroke_fill="white")
    return preview


def _validate_presets(presets):
    if not isinstance(presets, dict):
        raise ValueError("设备预设文件必须是按设备ID保存的JSON对象。")
    for device_id, preset in presets.items():
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("设备预设中存在空设备ID。")
        if device_id != device_id.strip():
            raise ValueError("设备ID的开头和结尾不能有空格。")
        if not isinstance(preset, dict):
            raise ValueError(f"设备“{device_id}”的预设格式不正确。")
        try:
            _roi_checked(preset["roi"], preset["width"], preset["height"])
        except KeyError as exc:
            raise ValueError(f"设备“{device_id}”的预设缺少字段：{exc.args[0]}。") from exc
    return presets


def load_presets(path) -> dict:
    """首次没有配置时返回空字典；损坏配置明确报错，避免覆盖。"""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        presets = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("设备预设JSON已损坏，请先修复或另存备份，程序不会覆盖它。") from exc
    return _validate_presets(presets)


def save_preset(path, device_id, width, height, roi) -> None:
    """保留其他设备，用同目录临时文件原子替换配置。"""
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("请先填写设备ID。")
    device_id = device_id.strip()
    checked_roi = _roi_checked(roi, width, height)
    path = Path(path)
    presets = load_presets(path)
    presets[device_id] = {"width": width, "height": height,
                          "roi": list(checked_roi)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, prefix=".roi_presets_",
                                         suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(presets, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def matching_preset(presets, device_id, width, height) -> tuple | None:
    """只有设备ID与转正后的图片尺寸都一致，才能沿用原ROI。"""
    _positive_int(width, "图片宽度")
    _positive_int(height, "图片高度")
    _validate_presets(presets)
    if not isinstance(device_id, str):
        return None
    preset = presets.get(device_id.strip())
    if preset is None or (preset["width"], preset["height"]) != (width, height):
        return None
    return _roi_checked(preset["roi"], width, height)


def _manifest_checked(manifest_path):
    """只读清单元数据与验证路径，不打开JPEG或提前检查其尺寸。"""
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = load_ui_manifest(manifest_path)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("图片清单不是有效的UTF-8 JSON。") from exc
    if not isinstance(manifest, dict):
        raise ValueError("图片清单必须是JSON对象。")
    width = _positive_int(manifest.get("width"), "清单图片宽度")
    height = _positive_int(manifest.get("height"), "清单图片高度")
    if not isinstance(manifest.get("image_id"), str) or not manifest["image_id"]:
        raise ValueError("清单缺少有效的image_id。")
    packets = manifest.get("packets")
    if not isinstance(packets, list):
        raise ValueError("清单中的packets必须是列表。")
    expected_ids = {"thumb"} | {f"tile_{i:02d}" for i in range(16)}
    packet_map = {}
    for packet in packets:
        if not isinstance(packet, dict):
            raise ValueError("清单中的图片包格式不正确。")
        packet_id = packet.get("packet_id")
        if not isinstance(packet_id, str) or packet_id not in expected_ids or packet_id in packet_map:
            raise ValueError("图片包编号错误或重复，应为thumb和tile_00至tile_15。")
        bbox = _roi_checked(packet.get("bbox"), width, height)
        priority = packet.get("priority")
        valid_priority = (0,) if packet_id == "thumb" else (1, 2)
        if isinstance(priority, bool) or not isinstance(priority, int) or priority not in valid_priority:
            raise ValueError(f"{packet_id}的priority不正确。")
        if packet_id == "thumb" and bbox != (0, 0, width, height):
            raise ValueError("缩略图的bbox必须覆盖整张图片。")
        _positive_int(packet.get("nbytes"), f"{packet_id}的nbytes")
        file_name = packet.get("file")
        if not isinstance(file_name, str) or not file_name:
            raise ValueError(f"{packet_id}缺少相对文件路径。")
        relative = Path(file_name)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError("JPEG路径必须位于清单目录内，不能使用绝对路径或上级目录。")
        file_path = (manifest_path.parent / relative).resolve()
        try:
            file_path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise ValueError("JPEG路径不能指向清单目录之外。") from exc
        packet_map[packet_id] = (packet, file_path)
    if set(packet_map) != expected_ids:
        raise ValueError("清单必须包含1张缩略图和完整的16个图片块。")
    if not any(packet["priority"] == 1 for packet, _ in packet_map.values()):
        raise ValueError("清单至少需要一个priority=1的重点块。")
    return manifest, packet_map


def _nonnegative_time(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}必须是非负秒数。")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name}必须是有限的非负秒数。")
    return float(value)


def _events_checked(events, packet_map):
    if not isinstance(events, (list, tuple)):
        raise ValueError("events必须是到达事件列表。")
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("到达事件必须是字典。")
        packet_id = event.get("packet_id")
        if not isinstance(packet_id, str) or packet_id not in packet_map or packet_id in seen:
            raise ValueError("到达事件包含未知或重复的图片包编号。")
        seen.add(packet_id)
        _nonnegative_time(event.get("arrival_s"), "arrival_s")
        packet = packet_map[packet_id][0]
        for key in ("nbytes", "priority"):
            if key in event and event[key] != packet[key]:
                raise ValueError(f"事件{packet_id}的{key}与清单不一致。")
    return events


def render_received(manifest_path, events, t) -> tuple[Image.Image, dict]:
    """恢复时刻t的接收画面；decode_ms表示本次恢复耗时，不是累计时延。"""
    t = _nonnegative_time(t, "模拟时刻t")
    manifest, packet_map = _manifest_checked(manifest_path)
    events = _events_checked(events, packet_map)
    width, height = manifest["width"], manifest["height"]
    received = {event["packet_id"] for event in events if event["arrival_s"] <= t}
    canvas = Image.new("RGB", (width, height), (235, 235, 235))
    elapsed = 0.0
    # 先铺已到达的缩略图，再覆盖已到达的图块，不受事件列表排列影响。
    ordered = (["thumb"] if "thumb" in received else [])
    ordered += sorted(packet_id for packet_id in received if packet_id != "thumb")
    for packet_id in ordered:
        packet, file_path = packet_map[packet_id]
        payload = file_path.read_bytes()  # 只在包完整到达后读取文件。
        if len(payload) != packet["nbytes"]:
            raise ValueError(f"{packet_id}的实际字节数与清单不一致。")
        started = time.perf_counter()
        with Image.open(io.BytesIO(payload)) as decoded:
            if decoded.format != "JPEG":
                raise ValueError(f"{packet_id}必须是JPEG文件。")
            x0, y0, x1, y1 = packet["bbox"]
            if packet_id == "thumb":
                tw, th = decoded.size
                if tw > width or th > height or max(tw, th) > 256:
                    raise ValueError("缩略图尺寸超过原图或256像素上限。")
                if abs(tw - width * th / height) > 1 and abs(th - height * tw / width) > 1:
                    raise ValueError("缩略图宽高比例与原图不一致。")
                if "encoded_size" in packet and tuple(packet["encoded_size"]) != decoded.size:
                    raise ValueError("缩略图实际尺寸与encoded_size不一致。")
                tile = decoded.convert("RGB").resize((width, height), Image.Resampling.BILINEAR)
                canvas.paste(tile, (0, 0))
            else:
                if decoded.size != (x1 - x0, y1 - y0):
                    raise ValueError(f"{packet_id}的JPEG尺寸与bbox不一致。")
                canvas.paste(decoded.convert("RGB"), (x0, y0))
        elapsed += time.perf_counter() - started
    roi_ids = {packet_id for packet_id, (packet, _) in packet_map.items()
               if packet["priority"] == 1}
    stats = {
        "received_bytes": sum(packet_map[packet_id][0]["nbytes"] for packet_id in received),
        "tiles_received": sum(packet_id != "thumb" for packet_id in received),
        "roi_complete": roi_ids.issubset(received),
        "decode_ms": elapsed * 1000.0,
    }
    return canvas, stats


def events_csv(manifest_path, result, mode, rate_mbps, source_label) -> bytes:
    """导出带BOM的UTF-8 CSV，保留测试来源标识，便于Excel打开。"""
    manifest, packet_map = _manifest_checked(manifest_path)
    if not isinstance(result, dict) or "events" not in result:
        raise ValueError("result必须包含events列表。")
    events = _events_checked(result["events"], packet_map)
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("请提供传输方式名称。")
    if _nonnegative_time(rate_mbps, "有效速率") <= 0:
        raise ValueError("有效速率必须大于0。")
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("请提供图片来源；接口测试图片必须保留测试标识。")
    output = io.StringIO(newline="")
    columns = ["image_id", "source_label", "mode", "rate_mbps", "packet_id",
               "priority", "nbytes", "start_s", "arrival_s", "cumulative_bytes"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    cumulative_bytes = 0
    for event in events:
        packet = packet_map[event["packet_id"]][0]
        start = _nonnegative_time(event.get("start_s"), "start_s")
        arrival = _nonnegative_time(event["arrival_s"], "arrival_s")
        if arrival < start:
            raise ValueError("到达时间不能早于开始时间。")
        cumulative_bytes += packet["nbytes"]
        if event.get("cumulative_bytes") != cumulative_bytes:
            raise ValueError("事件的累计字节数与当前发送顺序不一致。")
        writer.writerow({
            "image_id": manifest["image_id"], "source_label": source_label,
            "mode": mode, "rate_mbps": rate_mbps, "packet_id": event["packet_id"],
            "priority": packet["priority"], "nbytes": packet["nbytes"],
            "start_s": start, "arrival_s": arrival,
            "cumulative_bytes": cumulative_bytes,
        })
    return output.getvalue().encode("utf-8-sig")
