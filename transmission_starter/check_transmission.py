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
            for rate in (0, -1, float("nan"), float("inf"), True, "1"):
                rejects(rate=rate)
            rejects(mode="A")
        case("非法速率和模式被拒绝", rates)
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
    print(f"完成：{passed}/{passed} 项检查通过；未运行真实图片实验。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", help="可选：接入队友的真实清单，严格核对字节")
    parser.add_argument("--rate", type=float, default=1)
    args = parser.parse_args()
    try:
        run_tests()
        if args.manifest:
            b, c = check_pair(args.manifest, args.rate)
            print("[通过] 指定文件清单的字节、排序、B/C 一致性与计时检查")
            print(f"总字节数：{b['total_bytes']}；整图完成：{b['image_complete_s']:.6f} 秒")
            print(f"ROI 完成 B={b['roi_complete_s']} 秒，C={c['roi_complete_s']} 秒")
    except (AssertionError, ValueError, OSError) as exc:
        parser.exit(1, f"[失败] {exc}\n")


if __name__ == "__main__":
    main()
