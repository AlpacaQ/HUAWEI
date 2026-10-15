"""固定有效速率的 A/B/C 串行传输模拟，直接读取团队已有图片清单。"""
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
    if data.get("group") == "A":
        # A 组整图是一个文件；收齐后才有完整 ROI 和完整图片。
        if not isinstance(data.get("image_id"), str) or not data["image_id"]:
            raise ValueError("A 组需要非空 image_id")
        if any(type(data.get(k)) is not int or data[k] <= 0 for k in ("width", "height")):
            raise ValueError("A 组 width/height 必须为正整数")
        if "thumbnail" in data or "tiles" in data:
            raise ValueError("A 组清单不能同时包含缩略图或分块")
        items = [{"id": "full", "is_roi": True,
                  "path": data.get("payload"), "bytes": data.get("size_bytes")}]
    else:
        if data.get("group") not in (None, "B", "C"):
            raise ValueError("不支持的图片清单 group")
        thumbnail = data.get("thumbnail")
        tiles = data.get("tiles")
        if "packets" in data:
            # 早期界面清单的 priority 与图片包含义不同，显式映射，避免混用。
            if thumbnail is not None or tiles is not None:
                raise ValueError("不能混用 packets 与 thumbnail/tiles 两种清单")
            packets = data["packets"]
            if not isinstance(packets, list) or len(packets) != 17 or any(not isinstance(p, dict) for p in packets):
                raise ValueError("旧界面 packets 必须包含 17 个条目")
            ids = [packet.get("packet_id") for packet in packets]
            expected = {"thumb"} | {f"tile_{i:02d}" for i in range(16)}
            if any(not isinstance(i, str) for i in ids) or set(ids) != expected:
                raise ValueError("packets 必须包含 thumb 和 tile_00 至 tile_15，不能重复或遗漏")
            tiles = []
            for packet in packets:
                is_thumb = packet["packet_id"] == "thumb"
                priority = packet.get("priority")
                if type(priority) is not int or priority not in ((0,) if is_thumb else (1, 2)):
                    raise ValueError("旧界面 priority 必须为 0 缩略图、1 重点或 2 背景")
                item = {"id": packet["packet_id"], "path": packet.get("file"),
                        "bytes": packet.get("nbytes"), "is_roi": priority == 1}
                if is_thumb:
                    thumbnail = item
                else:
                    tiles.append(item)
        if not isinstance(thumbnail, dict) or not isinstance(tiles, list):
            raise ValueError("B/C 组需要 thumbnail 字典和 tiles 列表")
        if len(tiles) != 16 or any(not isinstance(t, dict) for t in tiles):
            raise ValueError("必须恰好包含 16 个 tile 字典")
        # 新图片包使用 tile_id/payload/size_bytes/priority；旧接口继续兼容。
        canonical = any("tile_id" in tile for tile in tiles) or "payload" in thumbnail
        if canonical:
            ids = [tile.get("tile_id") for tile in tiles]
            if any(type(i) is not int for i in ids) or set(ids) != set(range(16)):
                raise ValueError("tile_id 必须为整数 0 至 15，不能重复或遗漏")
            items = [{"id": "thumbnail", "is_roi": False,
                      "path": thumbnail.get("payload"), "bytes": thumbnail.get("size_bytes")}]
            for tile in tiles:
                if type(tile.get("priority")) is not int or tile["priority"] not in (0, 1):
                    raise ValueError("图片包 priority 必须为整数：1 为重点，0 为背景")
                items.append({"id": f"tile_{tile['tile_id']:02d}",
                              "is_roi": tile["priority"] == 1,
                              "path": tile.get("payload"), "bytes": tile.get("size_bytes")})
        else:
            ids = [tile.get("id") for tile in tiles]
            expected = {f"tile_{i:02d}" for i in range(16)}
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
    if "total_size_bytes" in data:
        declared_total = data["total_size_bytes"]
        if type(declared_total) is not int or declared_total != sum(item["bytes"] for item in items):
            raise ValueError("total_size_bytes 与文件实际字节总量不符")
    return items


def simulate(manifest_path, rate_mbps, mode):
    """返回 mode/rate_mbps/timeline/total_bytes/roi_complete_s/image_complete_s。

    B/C 无 ROI 时 roi_complete_s 为 None，thumbnail 计入总量。
    A 只有 full 文件，ROI 可用时刻与整图到齐时刻相同；这不代表读数正确。
    """
    if isinstance(rate_mbps, bool) or not isinstance(rate_mbps, (int, float)):
        raise ValueError("rate_mbps 必须为有限正数")
    try:
        rate_bps = float(rate_mbps) * 1_000_000
    except OverflowError as exc:
        raise ValueError("速率超出支持范围") from exc
    if not math.isfinite(rate_bps) or rate_bps <= 0:
        raise ValueError("速率超出支持范围")
    if mode not in ("A", "B", "C"):
        raise ValueError("mode 仅支持 A、B 或 C")
    items = _read_manifest(manifest_path)
    is_full_image = len(items) == 1 and items[0]["id"] == "full"
    if (mode == "A") != is_full_image:
        raise ValueError("A 模式需要 A 组整图清单；B/C 模式需要分块清单")
    if is_full_image:
        ordered = items
    else:
        thumbnail, tiles = items[0], items[1:]
        if mode == "B":
            tiles.sort(key=lambda t: t["id"])
        else:
            tiles.sort(key=lambda t: (not t["is_roi"], t["id"]))
        ordered = [thumbnail] + tiles
    if not math.isfinite(sum(item["bytes"] for item in ordered) * 8 / rate_bps):
        raise ValueError("速率过低，完成时间超出支持范围")
    timeline = []
    cumulative = 0
    for sequence, item in enumerate(ordered):
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
    parser.add_argument("--mode", choices=["A", "B", "C"], required=True)
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
