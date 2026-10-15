"""直接运行接口检查；临时二进制占位文件并非 JPEG、并非实验结果。"""
import argparse
import copy
import csv
import json
import math
from pathlib import Path
import tempfile
from transmission import simulate, export_csv


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


def fixture(folder, roi):
    """故意倒序清单和不等大小，防止误用清单顺序/固定每块时长。"""
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for i in range(16):
        size = (i + 1) * 1000
        filename = f"tile_{i:02d}.bin"
        (folder / filename).write_bytes(b"x" * size)
        items.append({"id": f"tile_{i:02d}", "path": filename,
                      "bytes": size, "is_roi": i in roi})
    (folder / "thumbnail.bin").write_bytes(b"x" * 1000)
    data = {"test_only": True, "thumbnail": {"path": "thumbnail.bin", "bytes": 1000},
            "tiles": items[::-1]}
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest, data


def check_pair(manifest, rate):
    b, c = [simulate(manifest, rate, mode) for mode in ("B", "C")]
    expected = [f"tile_{i:02d}" for i in range(16)]
    require([t["id"] for t in b["timeline"]] == ["thumbnail"] + expected, "B 排序错误")
    roi = [t["id"] for t in b["timeline"] if t["is_roi"]]
    background = [i for i in expected if i not in roi]
    require([t["id"] for t in c["timeline"]] == ["thumbnail"] + roi + background, "C 排序错误")
    require(b["total_bytes"] == c["total_bytes"], "B/C 总字节数不同")
    require(b["image_complete_s"] == c["image_complete_s"], "B/C 整图时间不同")
    signatures = lambda r: sorted((t["id"], t["path"], t["bytes"], t["is_roi"]) for t in r["timeline"])
    require(signatures(b) == signatures(c), "B/C 文件或标注不相同")
    for result in (b, c):
        cumulative = 0
        for row in result["timeline"]:
            require(close(row["start_s"], cumulative * 8 / (rate * 1_000_000)), "开始时间错误")
            cumulative += row["bytes"]
            require(row["cumulative_bytes"] == cumulative, "累计字节错误")
            require(close(row["arrival_s"], cumulative * 8 / (rate * 1_000_000)), "到达时间错误")
        require(result["total_bytes"] == cumulative, "总字节数错误")
        times = [t["arrival_s"] for t in result["timeline"] if t["is_roi"]]
        require(result["roi_complete_s"] == (max(times) if times else None), "ROI 时间错误")
    if roi:
        require(c["roi_complete_s"] <= b["roi_complete_s"], "C ROI 时间意外增加")
    return b, c


def check_full(manifest, rate):
    result = simulate(manifest, rate, "A")
    require(len(result["timeline"]) == 1, "A 组必须只有一个整图文件")
    row = result["timeline"][0]
    require(row["id"] == "full" and row["is_roi"] is True, "A 组条目标识错误")
    require(row["start_s"] == 0 and row["sequence"] == 0, "A 组开始时间错误")
    require(row["bytes"] == row["cumulative_bytes"] == result["total_bytes"], "A 组字节总量错误")
    require(row["arrival_s"] == result["roi_complete_s"] == result["image_complete_s"], "A 组完成时间错误")
    require(close(row["arrival_s"], row["bytes"] * 8 / (rate * 1_000_000)), "A 组时间公式错误")
    return result


def run_tests():
    print("接口测试：所有占位文件和数字仅用于检查程序，不是实验结果。")
    passed = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        def case(name, fn):
            nonlocal passed
            fn()
            passed += 1
            print(f"[通过] {name}")
        manifest, data = fixture(root / "late", {10, 15})
        def late():
            b, c = check_pair(manifest, 1)
            require(b["total_bytes"] == 137000, "测试总量错误")
            require(close(b["image_complete_s"], 1.096), "1 Mbps 换算错误")
            require(close(b["roi_complete_s"], 1.096) and close(c["roi_complete_s"], .224), "已知 ROI 时间错误")
        case("乱序输入、重点靠后、同文件、无遗漏及已知时间", late)
        def scenario(name, roi, equal=False):
            path, _ = fixture(root / name, roi)
            b, c = check_pair(path, .25)
            if equal:
                require(b["roi_complete_s"] == c["roi_complete_s"], "不应人为制造改善")
        case("重点原本靠前：改善为零", lambda: scenario("early", {0, 1}, True))
        case("全部重点：改善为零", lambda: scenario("all", set(range(16)), True))
        case("无重点：ROI 时间为 None", lambda: scenario("none", set(), True))
        def scaling():
            a = simulate(manifest, .5, "C")
            b = simulate(manifest, 1, "C")
            require(close(a["image_complete_s"], 2*b["image_complete_s"]), "速率缩放错误")
            require(close(a["roi_complete_s"], 2*b["roi_complete_s"]), "ROI 速率缩放错误")
        case("有效速率减半，时间加倍", scaling)
        def rejects(path=manifest, rate=1, mode="B"):
            try:
                simulate(path, rate, mode)
            except (ValueError, OSError):
                return
            raise AssertionError("错误输入未被拒绝")
        def rates():
            for rate in (0, -1, float("nan"), float("inf"), True, "1", 10**1000, 1e-323):
                rejects(rate=rate)
            rejects(mode="D")
            rejects(mode="A")
        case("非法速率、模式及分块清单使用 A 模式被拒绝", rates)
        def corrupted():
            for kind in ("size", "missing", "duplicate_id", "duplicate_path", "roi_type", "escape"):
                d = copy.deepcopy(data)
                if kind == "size": d["tiles"][0]["bytes"] += 1
                elif kind == "missing": d["tiles"][0]["path"] = "absent.bin"
                elif kind == "duplicate_id": d["tiles"][0]["id"] = d["tiles"][1]["id"]
                elif kind == "duplicate_path":
                    d["tiles"][0]["path"] = d["tiles"][1]["path"]
                    d["tiles"][0]["bytes"] = d["tiles"][1]["bytes"]
                elif kind == "roi_type": d["tiles"][0]["is_roi"] = "false"
                else: d["tiles"][0]["path"] = "../outside.bin"
                path = manifest.parent / "bad.json"
                path.write_text(json.dumps(d), encoding="utf-8")
                rejects(path)
        case("大小错误、缺失、重复、错误标注及越界路径被拒绝", corrupted)
        def csv_test():
            result = simulate(manifest, 1, "C")
            path = root / "output.csv"
            export_csv(result, path)
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            require(len(rows) == 17, "CSV 行数错误")
            require([r["id"] for r in rows] == [r["id"] for r in result["timeline"]], "CSV 顺序错误")
            require(close(float(rows[-1]["arrival_s"]), result["image_complete_s"]), "CSV 时间错误")
        case("CSV 导出 17 行及时间数值正确", csv_test)
        canonical = {
            "image_id": "test_only", "total_size_bytes": 137000,
            "thumbnail": {"payload": "thumbnail.bin", "size_bytes": 1000},
            "tiles": [{"tile_id": int(t["id"][-2:]), "payload": t["path"],
                       "size_bytes": t["bytes"], "priority": int(t["is_roi"])} for t in data["tiles"]],
        }
        canonical_path = manifest.parent / "canonical.json"
        canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
        def canonical_test():
            before = {p.name: p.read_bytes() for p in manifest.parent.iterdir() if p.is_file()}
            for rate in (.25, 1, 5):
                check_pair(canonical_path, rate)
                for mode in ("B", "C"):
                    require(simulate(canonical_path, rate, mode) == simulate(manifest, rate, mode),
                            "规范图片包与旧接口语义不一致")
            after = {p.name: p.read_bytes() for p in manifest.parent.iterdir() if p.is_file()}
            require(before == after, "仿真修改了图片包内容或创建了派生文件")
        case("规范图片包三档速率与旧接口一致，读取不改动任何文件", canonical_test)
        def bad_canonical():
            for kind in ("id_bool", "id_string", "id_duplicate", "priority_bool", "priority_two", "total", "size_bool", "count"):
                d = copy.deepcopy(canonical)
                if kind == "id_bool": d["tiles"][0]["tile_id"] = True
                elif kind == "id_string": d["tiles"][0]["tile_id"] = "15"
                elif kind == "id_duplicate": d["tiles"][0]["tile_id"] = d["tiles"][1]["tile_id"]
                elif kind == "priority_bool": d["tiles"][0]["priority"] = True
                elif kind == "priority_two": d["tiles"][0]["priority"] = 2
                elif kind == "total": d["total_size_bytes"] += 1
                elif kind == "size_bool": d["tiles"][0]["size_bytes"] = True
                else: d["tiles"].pop()
                path = manifest.parent / "bad_canonical.json"
                path.write_text(json.dumps(d), encoding="utf-8")
                rejects(path)
        case("规范图片包错误编号、priority、总量和条目数被拒绝", bad_canonical)
        def old_packets():
            packets = [{"packet_id": "thumb", "file": "thumbnail.bin", "nbytes": 1000, "priority": 0}]
            packets += [{"packet_id": t["id"], "file": t["path"], "nbytes": t["bytes"],
                         "priority": 1 if t["is_roi"] else 2} for t in data["tiles"]]
            path = manifest.parent / "packets.json"
            path.write_text(json.dumps({"packets": packets[::-1]}), encoding="utf-8")
            for mode in ("B", "C"):
                require(simulate(path, 1, mode) == simulate(manifest, 1, mode), "旧界面 packets 映射错误")
            packets[0]["priority"] = 1
            path.write_text(json.dumps({"packets": packets}), encoding="utf-8")
            rejects(path)
        case("旧界面 packets 清单保持兼容，缩略图优先级不能混淆", old_packets)
        a_folder = root / "full"
        a_folder.mkdir()
        (a_folder / "full.bin").write_bytes(b"x" * 125000)
        a_data = {"group": "A", "image_id": "test_only", "payload": "full.bin",
                  "size_bytes": 125000, "total_size_bytes": 125000, "width": 800, "height": 600}
        a_path = a_folder / "manifest_A.json"
        a_path.write_text(json.dumps(a_data), encoding="utf-8")
        def a_test():
            for rate in (.25, 1, 5):
                check_full(a_path, rate)
            result = check_full(a_path, 1)
            require(result["image_complete_s"] == 1, "A 组已知整图时间错误")
            csv_path = root / "A.csv"
            export_csv(result, csv_path)
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            require(len(rows) == 1 and rows[0]["id"] == "full", "A CSV 行数或文件标识错误")
        case("A 组单文件三档计时、完整到齐判据和 CSV", a_test)
        def bad_a():
            for mode in ("B", "C"):
                rejects(a_path, mode=mode)
            for kind in ("size", "path", "width", "image_id", "mixed"):
                d = copy.deepcopy(a_data)
                if kind == "size": d["size_bytes"] += 1
                elif kind == "path": d["payload"] = "../late/tile_00.bin"
                elif kind == "width": d["width"] = True
                elif kind == "image_id": d["image_id"] = ""
                else: d["tiles"] = []
                path = a_folder / "bad.json"
                path.write_text(json.dumps(d), encoding="utf-8")
                rejects(path, mode="A")
        case("A 清单与模式错配、字段错误或混用分块被拒绝", bad_a)
    print(f"完成：{passed}/{passed} 项检查通过；未运行真实图片实验。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", help="可选：接入队友的真实清单，严格核对字节")
    parser.add_argument("--rate", type=float, default=1)
    args = parser.parse_args()
    try:
        run_tests()
        if args.manifest:
            with Path(args.manifest).open(encoding="utf-8-sig") as f:
                supplied = json.load(f)
            if isinstance(supplied, dict) and supplied.get("group") == "A":
                a = check_full(args.manifest, args.rate)
                print("[通过] 指定 A 组清单的字节、单文件与计时检查")
                print(f"总字节数：{a['total_bytes']}；整图及 ROI 完成：{a['image_complete_s']:.6f} 秒")
            else:
                b, c = check_pair(args.manifest, args.rate)
                print("[通过] 指定文件清单的字节、排序、B/C 一致性与计时检查")
                print(f"总字节数：{b['total_bytes']}；整图完成：{b['image_complete_s']:.6f} 秒")
                print(f"ROI 完成 B={b['roi_complete_s']} 秒，C={c['roi_complete_s']} 秒")
    except (AssertionError, ValueError, OSError) as exc:
        parser.exit(1, f"[失败] {exc}\n")


if __name__ == "__main__":
    main()
