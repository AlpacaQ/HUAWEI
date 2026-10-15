"""读取并核验队友已经编码好的五张图片包，不重新编码、不修改交付目录。

这里是发送端的入库检查：读取文件字节来核对 SHA256 和大小，不解码 JPEG。
接收端仍单独遵守“完整到达后才能解码显示”的规则。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from team_bridge import REPOSITORY_ROOT, load_ui_manifest


def _json(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON顶层必须为字典：{path.name}")
    return data


def _inside(root, value):
    """目录中的每个路径都必须留在对应的交付目录中。"""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("交付路径必须为使用 / 的相对路径。")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("交付路径不能越出图片包目录。")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("交付路径不能越出图片包目录。")
    if not path.is_file():
        raise FileNotFoundError(f"图片包缺少文件：{path}")
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_hash(path, expected):
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError(f"SHA256字段无效：{path.name}")
    actual = _sha(path)
    if actual != expected:
        raise ValueError(f"SHA256核验失败，文件内容与交付清单不同：{path.name}")
    return actual


def _entries(index, label):
    images = index.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError(f"{label}缺少图片列表。")
    if type(index.get("image_count")) is not int or index["image_count"] != len(images):
        raise ValueError(f"{label}图片数量与索引不一致。")
    entries = {}
    for entry in images:
        if not isinstance(entry, dict):
            raise ValueError(f"{label}图片条目必须为字典。")
        image_id = entry.get("image_id")
        if not isinstance(image_id, str) or not image_id.strip() or image_id in entries:
            raise ValueError(f"{label}图片编号无效或重复。")
        entries[image_id] = entry
    return entries


def truth_information(ground_truth):
    """候选读数与人工确认分开；不把 use_for_reading_accuracy 当作确认依据。"""
    confirmation = ground_truth.get("human_confirmation")
    status = confirmation.get("status", "pending") if isinstance(confirmation, dict) else "pending"
    reading = ground_truth.get("reading_text")
    reading_available = isinstance(reading, str) and bool(reading.strip())
    confirmed = status == "confirmed" and reading_available and not ground_truth.get("unconfirmed_by_user", False)
    if status == "confirmed" and not confirmed:
        status = "pending"
    summary = ground_truth.get("answer_summary")
    if isinstance(summary, str) and summary.strip():
        answer = summary.strip()
    elif reading_available:
        unit = ground_truth.get("unit") or ""
        answer = f"{reading.strip()} {unit}".strip()
    else:
        answer = "无法确认"
    return {"truth_confirmed": confirmed, "truth_status": status, "answer_text": answer}


def list_shared_packages(repo_root=None):
    """返回已核验的配对图片列表；所有路径为绝对路径字符串。

    每项包含 image_id、manifest_bc、manifest_a、source_file、roi_preview、
    ground_truth（原始标注）、truth_confirmed、truth_status、answer_text、
    roi、width、height、quality，以及 metadata 中的字节数和来源/清单/载荷哈希。
    无缓存：每次调用检查当前文件；界面可按需要保存一次已核验运行的结果。
    """
    root = Path(repo_root or REPOSITORY_ROOT).resolve()
    bc_root = root / "inspection_image" / "delivery_v2"
    a_root = root / "inspection_image" / "delivery_A_v1"
    bc_index_path = bc_root / "package_index.json"
    a_index_path = a_root / "package_index_A.json"
    bc_index, a_index = _json(bc_index_path), _json(a_index_path)
    bc_entries, a_entries = _entries(bc_index, "B/C索引"), _entries(a_index, "A索引")
    if set(bc_entries) != set(a_entries):
        raise ValueError("A组与B/C组的图片编号集合不一致。")
    if a_index.get("schema_version") != 1 or a_index.get("group") != "A":
        raise ValueError("A组索引版本或分组标记不正确。")
    if type(a_index.get("quality")) is not int:
        raise ValueError("A组索引缺少整数JPEG质量。")
    if bc_index.get("transmission_jpeg_count") != 17 * len(bc_entries):
        raise ValueError("B/C索引JPEG数量应为每张图片17个。")
    index_hash_bc, index_hash_a = _sha(bc_index_path), _sha(a_index_path)
    result = []
    for image_id, bc_entry in bc_entries.items():
        a_entry = a_entries[image_id]
        bc_path = _inside(bc_root, bc_entry.get("manifest"))
        a_path = _inside(a_root, a_entry.get("manifest"))
        bc_manifest, a_manifest = load_ui_manifest(bc_path), load_ui_manifest(a_path)
        a_source = _json(a_path)
        if bc_manifest.get("group") == "A" or a_manifest.get("group") != "A":
            raise ValueError(f"{image_id}：A与B/C清单类型不对应。")
        if bc_manifest["image_id"] != image_id or a_manifest["image_id"] != image_id:
            raise ValueError(f"{image_id}：图片编号与清单不一致。")
        if (bc_manifest["width"], bc_manifest["height"]) != (a_manifest["width"], a_manifest["height"]):
            raise ValueError(f"{image_id}：A组与B/C组尺寸不一致。")
        quality = a_manifest["packets"][0]["quality"]
        if quality != a_index["quality"] or any(p["quality"] != quality for p in bc_manifest["packets"] if p["packet_id"] != "thumb"):
            raise ValueError(f"{image_id}：A组与B/C块的JPEG质量不一致。")
        source_file = _inside(bc_root, bc_entry.get("source_file"))
        source_hash = _check_hash(source_file, bc_entry.get("source_sha256"))
        if a_source.get("source_sha256") != source_hash:
            raise ValueError(f"{image_id}：A组来源SHA256与B/C原图不一致。")
        hashes_bc = bc_entry.get("payload_sha256")
        if not isinstance(hashes_bc, dict) or set(hashes_bc) != {p["file"] for p in bc_manifest["packets"]}:
            raise ValueError(f"{image_id}：B/C载荷SHA256列表不完整。")
        for packet in bc_manifest["packets"]:
            path = _inside(bc_path.parent, packet["file"])
            if path.stat().st_size != packet["nbytes"]:
                raise ValueError(f"{image_id}：B/C实际字节数与清单不一致。")
            _check_hash(path, hashes_bc[packet["file"]])
        full = a_manifest["packets"][0]
        full_path = _inside(a_path.parent, full["file"])
        if _inside(a_root, a_entry.get("payload")) != full_path:
            raise ValueError(f"{image_id}：A组索引与清单的JPEG路径不一致。")
        if full_path.stat().st_size != full["nbytes"] or a_entry.get("size_bytes") != full["nbytes"]:
            raise ValueError(f"{image_id}：A组实际字节数与清单不一致。")
        full_hash = _check_hash(full_path, a_source.get("payload_sha256"))
        if bc_entry.get("total_size_bytes") != bc_manifest["total_size_bytes"]:
            raise ValueError(f"{image_id}：B/C索引总字节数与清单不一致。")
        roi_tile_ids = sorted(int(p["packet_id"][-2:]) for p in bc_manifest["packets"] if p["priority"] == 1)
        if bc_entry.get("priority_tile_ids") != roi_tile_ids:
            raise ValueError(f"{image_id}：B/C索引重点块与清单不一致。")
        ground_truth_path = _inside(bc_root, bc_entry.get("ground_truth"))
        ground_truth = _json(ground_truth_path)
        if ground_truth.get("image_id") != image_id or ground_truth.get("roi") != bc_manifest["roi"]:
            raise ValueError(f"{image_id}：标注的编号或ROI与图片清单不一致。")
        if ground_truth.get("processed_size") != [bc_manifest["width"], bc_manifest["height"]]:
            raise ValueError(f"{image_id}：标注的图像尺寸与清单不一致。")
        roi_preview = _inside(bc_root, bc_entry.get("roi_preview"))
        result.append({
            "image_id": image_id, "manifest_bc": str(bc_path), "manifest_a": str(a_path),
            "source_file": str(source_file), "roi_preview": str(roi_preview),
            "ground_truth": ground_truth, **truth_information(ground_truth),
            "roi": bc_manifest["roi"], "width": bc_manifest["width"],
            "height": bc_manifest["height"], "quality": quality,
            "metadata": {
                "source_sha256": source_hash, "manifest_bc_sha256": _sha(bc_path),
                "manifest_a_sha256": _sha(a_path), "package_index_bc_sha256": index_hash_bc,
                "package_index_a_sha256": index_hash_a, "payload_sha256_bc": hashes_bc,
                "payload_sha256_a": full_hash, "total_bytes_bc": bc_manifest["total_size_bytes"],
                "total_bytes_a": a_manifest["total_size_bytes"], "ground_truth_sha256": _sha(ground_truth_path),
                "verification": "sha256_and_size_checked",
            },
        })
    for index, field, label in ((bc_index, "total_bytes_bc", "B/C"), (a_index, "total_bytes_a", "A")):
        if type(index.get("total_size_bytes")) is not int or index["total_size_bytes"] != sum(item["metadata"][field] for item in result):
            raise ValueError(f"{label}索引总字节数不等于全部图片之和。")
    return result
