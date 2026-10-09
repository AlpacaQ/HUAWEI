"""固定有效速率的串行传输模拟；接口为待团队对齐的 v1，见 README。"""
import argparse
import csv
import json
import math
from pathlib import Path


def _read_manifest(manifest_path):
    """核对清单、相对路径和实际字节数，不解码或重编码图片。"""
    manifest_path = Path(manifest_path).resolve()
    with manifest_path.open(encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest 顶层必须是字典")
    thumbnail = data.get("thumbnail")
    tiles = data.get("tiles")
    if not isinstance(thumbnail, dict) or not isinstance(tiles, list):
        raise ValueError("需要 thumbnail 字典和 tiles 列表（接口 v1）")
    expected = {f"tile_{i:02d}" for i in range(16)}
    if len(tiles) != 16 or any(not isinstance(t, dict) for t in tiles):
        raise ValueError("必须恰好包含 16 个 tile 字典")
    ids = [t.get("id") for t in tiles]
    if any(not isinstance(i, str) for i in ids) or set(ids) != expected:
        raise ValueError("tile 编号必须为 tile_00 至 tile_15，不能重复或遗漏")
    items = [dict(thumbnail, id="thumbnail", is_roi=False)]
    for tile in tiles:
        if type(tile.get("is_roi")) is not bool:
            raise ValueError(f"{tile['id']} 的 is_roi 必须为 JSON true/false")
        items.append(dict(tile))
    seen = set()
    for item in items:
        relative = item.get("path")
        declared = item.get("bytes")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"{item['id']} 缺少 path")
        path = Path(relative)
        if path.is_absolute() or "\\" in relative or ":" in relative:
            raise ValueError("path 必须使用相对路径和 / 分隔符")
        actual_path = (manifest_path.parent / path).resolve()
        if not actual_path.is_relative_to(manifest_path.parent):
            raise ValueError("文件路径不能越出清单目录")
        if actual_path in seen:
            raise ValueError("不同条目不能指向同一个文件")
        seen.add(actual_path)
        if type(declared) is not int or declared <= 0:
            raise ValueError(f"{item['id']} 的 bytes 必须为正整数")
        if not actual_path.is_file():
            raise FileNotFoundError(f"找不到 {item['id']} 文件：{relative}")
        actual = actual_path.stat().st_size
        if actual != declared:
            raise ValueError(f"{item['id']} 字节数不符：清单 {declared}，实际 {actual}")
        item["bytes"] = actual
    return items


def simulate(manifest_path, rate_mbps, mode):
    """返回 mode/rate_mbps/timeline/total_bytes/roi_complete_s/image_complete_s。

    无 ROI 时 roi_complete_s 为 None。thumbnail 计入时间和总字节数。
    """
    if isinstance(rate_mbps, bool) or not isinstance(rate_mbps, (int, float)):
        raise ValueError("rate_mbps 必须为有限正数")
    if not math.isfinite(rate_mbps) or rate_mbps <= 0:
        raise ValueError("rate_mbps 必须为有限正数")
    rate_bps = rate_mbps * 1_000_000
    if not math.isfinite(rate_bps) or rate_bps <= 0:
        raise ValueError("速率超出支持范围")
    if mode not in ("B", "C"):
        raise ValueError("mode 仅支持 B 或 C")
    items = _read_manifest(manifest_path)
    thumbnail, tiles = items[0], items[1:]
    if mode == "B":
        tiles.sort(key=lambda t: t["id"])
    else:
        tiles.sort(key=lambda t: (not t["is_roi"], t["id"]))
    timeline = []
    cumulative = 0
    for sequence, item in enumerate([thumbnail] + tiles):
        start = cumulative * 8 / rate_bps
        cumulative += item["bytes"]
        timeline.append({"sequence": sequence, "id": item["id"],
                         "path": item["path"], "is_roi": item["is_roi"],
                         "bytes": item["bytes"], "cumulative_bytes": cumulative,
                         "start_s": start, "arrival_s": cumulative * 8 / rate_bps})
    roi_times = [t["arrival_s"] for t in timeline if t["is_roi"]]
    return {"mode": mode, "rate_mbps": rate_mbps, "timeline": timeline,
            "total_bytes": cumulative,
            "roi_complete_s": max(roi_times) if roi_times else None,
            "image_complete_s": cumulative * 8 / rate_bps}


def export_csv(result, csv_path):
    """导出完整时间表，每行附带模式、速率和汇总指标，秒值不人为截断。"""
    metadata = {k: v for k, v in result.items() if k != "timeline"}
    fields = list(metadata) + list(result["timeline"][0])
    with Path(csv_path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in result["timeline"]:
            writer.writerow(dict(metadata, **row))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_path")
    parser.add_argument("--rate", type=float, required=True, help="有效速率 Mbps")
    parser.add_argument("--mode", choices=["B", "C"], required=True)
    parser.add_argument("--csv", help="CSV 输出路径")
    args = parser.parse_args()
    try:
        result = simulate(args.manifest_path, args.rate, args.mode)
        if args.csv:
            export_csv(result, args.csv)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
