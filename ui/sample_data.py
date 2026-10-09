"""读取公开仪表样本目录，并核对本地图片的完整性。

本模块只读本地文件，不联网、不下载、不改写样本或目录清单。
清单保存来源、参考读数与ROI；图片字节通过SHA256校验后才交给界面。
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re

from PIL import Image, ImageOps


def _required_text(mapping, key, context, *, allow_empty=False):
    value = mapping.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{context}的{key}必须是{'可为空的' if allow_empty else '非空'}字符串。")
    return value


def _image_path(project_root, file_name):
    """允许images内的相对路径；拒绝目录跳转和指向目录外的链接。"""
    project_root = Path(project_root).resolve()
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("样本file必须是images目录内的相对文件路径。")
    # 同时兼容清单中的正斜杠和Windows反斜杠。
    normalized = file_name.replace("\\", "/")
    parts = normalized.split("/")
    relative = Path(normalized)
    if (relative.is_absolute() or relative.drive or ":" in normalized
            or ".." in parts or len(parts) < 2 or parts[0] != "images"
            or any(part in ("", ".") for part in parts)):
        raise ValueError("样本file必须位于images目录内，不能使用绝对路径或上级目录。")
    image_path = (project_root / relative).resolve()
    try:
        image_path.relative_to(project_root / "images")
    except ValueError as exc:
        raise ValueError("样本图片路径指向了项目images目录之外。") from exc
    return image_path


def _validate_sample(project_root, sample):
    """只验证元数据与路径，不提前读取图片内容。"""
    if not isinstance(sample, dict):
        raise ValueError("samples中的每个样本必须是JSON对象。")
    sample_id = _required_text(sample, "sample_id", "样本")
    context = f"样本“{sample_id}”"
    if sample_id != sample_id.strip():
        raise ValueError("sample_id的开头和结尾不能有空格。")
    image_path = _image_path(project_root, sample.get("file"))
    _required_text(sample, "source_filename", context)
    digest = _required_text(sample, "sha256", context)
    if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise ValueError(f"{context}的sha256必须是64位十六进制字符串。")
    for key in ("width", "height"):
        value = sample.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{context}的{key}必须是正整数。")
    if "roi" not in sample:
        raise ValueError(f"{context}缺少roi字段；未标注时请填null。")
    roi = sample["roi"]
    if roi is not None:
        if (not isinstance(roi, list) or len(roi) != 4
                or any(isinstance(v, bool) or not isinstance(v, int) for v in roi)):
            raise ValueError(f"{context}的roi必须是4个整数的列表或null。")
        x0, y0, x1, y1 = roi
        if not (0 <= x0 < x1 <= sample["width"] and 0 <= y0 < y1 <= sample["height"]):
            raise ValueError(f"{context}的ROI越界或区域为空。")
    for key in ("roi_origin", "reference_reading", "reading_status"):
        _required_text(sample, key, context, allow_empty=True)
    return image_path


def load_sample_catalog(project_root) -> dict:
    """读取data/meter_samples.json；尚未准备样本时返回空目录。"""
    project_root = Path(project_root).resolve()
    catalog_path = project_root / "data" / "meter_samples.json"
    if not catalog_path.exists():
        return {"schema_version": 1,
                "dataset": {"name": "", "url": "", "license": ""},
                "samples": []}
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("仪表样本目录JSON损坏或编码不正确，请检查meter_samples.json。") from exc
    except OSError as exc:
        raise ValueError("无法读取仪表样本目录meter_samples.json。") from exc
    if not isinstance(catalog, dict):
        raise ValueError("仪表样本目录必须是JSON对象。")
    if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
        raise ValueError("仪表样本目录仅支持schema_version=1。")
    dataset = catalog.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("样本目录中的dataset必须是JSON对象。")
    for key in ("name", "url", "license"):
        _required_text(dataset, key, "数据集信息")
    samples = catalog.get("samples")
    if not isinstance(samples, list):
        raise ValueError("样本目录中的samples必须是列表。")
    seen_ids = set()
    seen_files = set()
    for sample in samples:
        image_path = _validate_sample(project_root, sample)
        sample_id = sample["sample_id"]
        # Windows路径不区分大小写；同一个文件不能重复登记。
        file_key = str(image_path).casefold()
        if sample_id in seen_ids:
            raise ValueError(f"样本目录存在重复的sample_id：{sample_id}。")
        if file_key in seen_files:
            raise ValueError(f"样本目录重复引用同一图片文件：{sample['file']}。")
        seen_ids.add(sample_id)
        seen_files.add(file_key)
    return catalog


def read_sample(project_root, sample) -> tuple[bytes, Image.Image]:
    """核对文件哈希，再按EXIF转正并检查尺寸；返回原始字节和RGB图片。"""
    image_path = _validate_sample(project_root, sample)
    try:
        payload = image_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取样本图片：{sample['file']}，请检查文件是否存在。") from exc
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != sample["sha256"].lower():
        raise ValueError(f"样本“{sample['sample_id']}”的SHA256校验失败，文件可能被修改或下载不完整。")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"样本“{sample['sample_id']}”无法解码为有效图片。") from exc
    expected_size = (sample["width"], sample["height"])
    if image.size != expected_size:
        raise ValueError(f"样本“{sample['sample_id']}”转正后的尺寸为{image.size}，与清单{expected_size}不一致。")
    return payload, image
