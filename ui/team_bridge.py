"""把两位队友的现有接口接到界面，不修改队友代码、不重新编码图片。

manifest.json 始终是图像模块生成的唯一原始清单。为兼容当前传输模块，
只在它旁边生成 manifest_for_transmission.json 字段视图；它不包含新图片，
不应手工编辑，也不是另一份独立的数据来源。到达时间仍由传输模块计算。
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path


# 1. 精确定位仓库中的队友模块，避免导入电脑里同名的其他文件。
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATHS = {
    "image_processing": "inspection_image/image_processing.py",
    "transmission": "transmission_starter/transmission.py",
}
TRANSMISSION_VIEW_NAME = "manifest_for_transmission.json"


def _module_fingerprint(name):
    path = REPOSITORY_ROOT / MODULE_PATHS[name]
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=8)
def _load_exact_module(path_text, sha256):
    """内容发生变化时重新导入；同一版本在界面重绘时复用。"""
    path = Path(path_text)
    spec = importlib.util.spec_from_file_location(f"roi_team_{path.stem}_{sha256}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法载入队友模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _team_module(name):
    path, digest = _module_fingerprint(name)
    return _load_exact_module(str(path), digest)


def backend_metadata():
    """日志保存实际模块路径及内容摘要，便于复现某次运行使用的版本。"""
    result = {"backend_kind": "team_modules_via_ui_bridge"}
    for name, relative in MODULE_PATHS.items():
        _, digest = _module_fingerprint(name)
        result[name] = {"path": relative, "sha256": digest}
    result["bridge"] = {
        "path": "ui/team_bridge.py",
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return result


# 2. 以下检查只读取清单元数据；此阶段不读取、解码或检查 JPEG 的文件大小。
# 真实大小由发送端的队友传输模块检查，接收端只能打开已经到达的图片块。
def _integer(value, label, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label}必须是范围有效的整数。")
    return value


def _bounds(value, width, height, label):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label}必须是4个整数坐标。")
    for coordinate in value:
        _integer(coordinate, label)
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"{label}越界或没有面积。")
    return list(value)


def _box_for_tile(tile_id, width, height):
    row, col = divmod(tile_id, 4)
    return [col * width // 4, row * height // 4,
            (col + 1) * width // 4, (row + 1) * height // 4]


def _intersects(box, roi):
    return (max(box[0], roi[0]) < min(box[2], roi[2])
            and max(box[1], roi[1]) < min(box[3], roi[3]))


def _relative_path(value, manifest_path, used_paths):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("JPEG路径必须使用相对路径和 / 分隔符。")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("JPEG路径不能越出清单目录。")
    resolved = (manifest_path.parent / relative).resolve()
    if not resolved.is_relative_to(manifest_path.parent):
        raise ValueError("JPEG路径不能指向清单目录之外。")
    if resolved in used_paths:
        raise ValueError("不同图片包不能指向同一个JPEG文件。")
    used_paths.add(resolved)
    return value


def _read_json(manifest_path):
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("图片清单必须是有效的UTF-8 JSON。") from exc
    if not isinstance(data, dict):
        raise ValueError("图片清单顶层必须是字典。")
    return data


def _validated_ui_view(data, manifest_path):
    """统一检查转换后的元数据，也兼容原独立演示后端的 packets 格式。"""
    width = _integer(data.get("width"), "图片宽度", 4)
    height = _integer(data.get("height"), "图片高度", 4)
    roi = _bounds(data.get("roi"), width, height, "ROI")
    if not isinstance(data.get("image_id"), str) or not data["image_id"].strip():
        raise ValueError("清单缺少有效的image_id。")
    packets = data.get("packets")
    if not isinstance(packets, list) or len(packets) != 17 or any(not isinstance(p, dict) for p in packets):
        raise ValueError("清单必须包含1张缩略图和16个图片块。")
    ids = [packet.get("packet_id") for packet in packets]
    expected_ids = {"thumb"} | {f"tile_{index:02d}" for index in range(16)}
    if any(not isinstance(value, str) for value in ids) or set(ids) != expected_ids:
        raise ValueError("图片包编号必须为thumb与tile_00至tile_15，不能缺失或重复。")
    used_paths = set()
    for packet in packets:
        packet_id = packet["packet_id"]
        box = _bounds(packet.get("bbox"), width, height, f"{packet_id}的bbox")
        expected_box = [0, 0, width, height] if packet_id == "thumb" else _box_for_tile(int(packet_id[-2:]), width, height)
        if box != expected_box:
            raise ValueError(f"{packet_id}的坐标不符合4×4分块规则。")
        priority = _integer(packet.get("priority"), f"{packet_id}的priority", 0, 2)
        expected_priority = 0 if packet_id == "thumb" else (1 if _intersects(box, roi) else 2)
        if priority != expected_priority:
            raise ValueError(f"{packet_id}的priority与ROI相交关系不一致。")
        _integer(packet.get("quality"), f"{packet_id}的quality", 0, 100)
        _integer(packet.get("nbytes"), f"{packet_id}的nbytes", 1)
        _relative_path(packet.get("file"), manifest_path, used_paths)
        if "encoded_size" in packet:
            encoded = packet["encoded_size"]
            if not isinstance(encoded, (list, tuple)) or len(encoded) != 2:
                raise ValueError(f"{packet_id}的encoded_size必须包含宽、高。")
            ew = _integer(encoded[0], "编码宽度", 1)
            eh = _integer(encoded[1], "编码高度", 1)
            if packet_id == "thumb":
                if ew > min(width, 256) or eh > min(height, 256):
                    raise ValueError("缩略图尺寸超过原图或256像素上限。")
                if abs(ew - width * eh / height) > 1 and abs(eh - height * ew / width) > 1:
                    raise ValueError("缩略图尺寸比例与原图不一致。")
            elif [ew, eh] != [box[2] - box[0], box[3] - box[1]]:
                raise ValueError(f"{packet_id}的encoded_size与bbox不一致。")
    if not any(packet["priority"] == 1 for packet in packets):
        raise ValueError("至少需要一个与ROI相交的重点块。")
    total = sum(packet["nbytes"] for packet in packets)
    if "total_size_bytes" in data:
        if _integer(data["total_size_bytes"], "total_size_bytes", 1) != total:
            raise ValueError("清单总字节数与17个JPEG的声明字节数之和不一致。")
    return data


def load_ui_manifest(manifest_path):
    """将原始清单映射成界面格式；不改写源文件、不提前读取JPEG。"""
    manifest_path = Path(manifest_path).resolve()
    source = _read_json(manifest_path)
    if "packets" in source:
        # 旧演示格式只供兼容界面自检；正式模式使用队友清单。
        return _validated_ui_view(source, manifest_path)
    if _integer(source.get("schema_version"), "schema_version", 1) != 1:
        raise ValueError("当前适配层只支持图像模块schema_version=1。")
    if source.get("grid") != {"rows": 4, "cols": 4} or source.get("mode") != "RGB":
        raise ValueError("当前适配层需要4×4 RGB图像清单。")
    image_id = source.get("image_id")
    width = _integer(source.get("width"), "图片宽度", 4)
    height = _integer(source.get("height"), "图片高度", 4)
    roi = _bounds(source.get("roi"), width, height, "ROI")
    thumbnail, tiles = source.get("thumbnail"), source.get("tiles")
    if not isinstance(thumbnail, dict) or not isinstance(tiles, list) or len(tiles) != 16:
        raise ValueError("图像清单必须包含thumbnail和16个tiles。")
    if thumbnail.get("image_id") != image_id:
        raise ValueError("缩略图的image_id与整图不一致。")
    packets = [{
        "packet_id": "thumb", "bbox": [0, 0, width, height], "priority": 0,
        "quality": thumbnail.get("quality"), "file": thumbnail.get("payload"),
        "nbytes": thumbnail.get("size_bytes"),
        "encoded_size": [thumbnail.get("width"), thumbnail.get("height")],
    }]
    seen_ids = set()
    for tile in tiles:
        if not isinstance(tile, dict):
            raise ValueError("每个tile必须是字典。")
        tile_id = _integer(tile.get("tile_id"), "tile_id", 0, 15)
        if tile_id in seen_ids or tile.get("image_id") != image_id:
            raise ValueError("图片块编号重复，或image_id与整图不一致。")
        seen_ids.add(tile_id)
        box = _bounds(tile.get("box"), width, height, f"tile_{tile_id:02d}的box")
        if box != _box_for_tile(tile_id, width, height):
            raise ValueError("图片块坐标与编号对应的4×4网格不一致。")
        for key, expected in zip(("x", "y", "w", "h"), (box[0], box[1], box[2] - box[0], box[3] - box[1])):
            if _integer(tile.get(key), key) != expected:
                raise ValueError(f"tile_{tile_id:02d}的{key}与box不一致。")
        priority = _integer(tile.get("priority"), "图像模块priority", 0, 1)
        if bool(priority) != _intersects(box, roi):
            raise ValueError("图片块priority与ROI相交关系不一致。")
        packets.append({
            "packet_id": f"tile_{tile_id:02d}", "bbox": box,
            "priority": 1 if priority == 1 else 2,
            "quality": tile.get("quality"), "file": tile.get("payload"),
            "nbytes": tile.get("size_bytes"), "encoded_size": [tile["w"], tile["h"]],
        })
    seconds = source.get("image_processing_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("image_processing_seconds必须是有限的非负秒数。")
    milliseconds = seconds * 1000.0
    if not math.isfinite(milliseconds):
        raise ValueError("图像处理耗时过大，无法转换成毫秒。")
    normalized = {
        "image_id": image_id, "width": width, "height": height, "roi": roi,
        "packets": packets, "total_size_bytes": source.get("total_size_bytes"),
        # 队友只测量了图像处理总耗时，不能虚构独立裁剪/编码耗时。
        "processing_ms": {"total_ms": milliseconds},
        "processing_note": "队友图像模块本机实测总耗时：读取、EXIF转正、裁剪、JPEG编码、写盘和长度读取；不含清单写盘。尚未分别测量裁剪与编码耗时。",
        "backend_kind": "team_modules_via_ui_bridge",
        "source_name": source.get("source_name", ""),
    }
    return _validated_ui_view(normalized, manifest_path)


# 3. 图像准备直接交给队友完成，返回原始 manifest.json，不产生第二批JPEG。
def prepare_image(image_path, roi, output_dir):
    manifest_path = _team_module("image_processing").prepare_image(image_path, roi, output_dir)
    load_ui_manifest(manifest_path)
    return str(Path(manifest_path).resolve())


# 4. 传输适配只改字段名字。B/C共用同一个视图，所有到达时间来自队友simulate。
def _transmission_view(manifest_path, manifest):
    if manifest_path.name == TRANSMISSION_VIEW_NAME:
        raise ValueError("请输入原始manifest.json，不要把派生的传输视图当成原始清单。")
    packets = {packet["packet_id"]: packet for packet in manifest["packets"]}
    thumb = packets["thumb"]
    view = {
        "_bridge": {
            "schema_version": 1,
            "source_manifest": manifest_path.name,
            "source_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "note": "由原始清单派生的字段视图；不手工编辑、不作为独立数据真值。",
        },
        "thumbnail": {"path": thumb["file"], "bytes": thumb["nbytes"]},
        "tiles": [{
            "id": f"tile_{index:02d}",
            "path": packets[f"tile_{index:02d}"]["file"],
            "bytes": packets[f"tile_{index:02d}"]["nbytes"],
            "is_roi": packets[f"tile_{index:02d}"]["priority"] == 1,
        } for index in range(16)],
    }
    path = manifest_path.parent / TRANSMISSION_VIEW_NAME
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(view, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except FileExistsError:
        if _read_json(path) != view:
            raise ValueError("已有manifest_for_transmission.json与原始清单不匹配，已拒绝覆盖。请检查清单是否被修改，并使用新的输出目录重新生成图片包。") from None
    return path


def simulate(manifest_path, rate_mbps, mode):
    """调用队友计时函数，再把timeline字段名映射成界面事件。"""
    manifest_path = Path(manifest_path).resolve()
    manifest = load_ui_manifest(manifest_path)
    view_path = _transmission_view(manifest_path, manifest)
    result = _team_module("transmission").simulate(str(view_path), rate_mbps, mode)
    packet_map = {packet["packet_id"]: packet for packet in manifest["packets"]}
    events = []
    for row in result["timeline"]:
        packet_id = "thumb" if row["id"] == "thumbnail" else row["id"]
        events.append({
            "packet_id": packet_id, "start_s": row["start_s"],
            "arrival_s": row["arrival_s"], "cumulative_bytes": row["cumulative_bytes"],
            "nbytes": row["bytes"], "priority": packet_map[packet_id]["priority"],
        })
    return {
        "mode": result["mode"], "rate_mbps": result["rate_mbps"],
        "events": events, "roi_complete_s": result["roi_complete_s"],
        "full_complete_s": result["image_complete_s"], "total_bytes": result["total_bytes"],
    }
