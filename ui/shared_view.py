"""共享图片包的页面：只读已有 JPEG，计算 A/B/C，并保存独立运行日志。"""

import json
import math
import uuid
from pathlib import Path

import streamlit as st

import team_bridge
from shared_package import list_shared_packages
from ui_support import events_csv, render_received


def show_shared_comparison(runtime_root: Path, check_bc_result) -> None:
    """1. 验收共同图片包；2. 计算时间表；3. 按同一时刻恢复；4. 导出记录。"""
    try:
        packages = list_shared_packages()
    except (ValueError, OSError, KeyError) as error:
        st.error(f"共享图片包验收失败：{error}")
        st.info("请下载完整仓库，保留 inspection_image 下的 delivery_v2 和 delivery_A_v1。")
        return
    if not packages:
        st.error("共享图片包中没有可比较的照片。")
        return
    by_id = {item["image_id"]: item for item in packages}
    with st.sidebar:
        image_id = st.selectbox("选择共享照片", list(by_id), key="shared_image")
        rate = st.selectbox("有效传输速率（Mbps）", [0.25, 1.0, 5.0], key="shared_rate")
        st.caption("固定有效速率、无丢包；计算 JPEG 载荷时间，尚未模拟完整 5G 链路。")
    package = by_id[image_id]
    st.info("直接使用队友交付的 JPEG 和 ROI。A 使用整图文件；B/C 共用同一批缩略图和 16 块，仅改变发送顺序。")
    st.write(f"当前图片：{image_id} · {package['width']} × {package['height']} 像素 · 固定 ROI：{package['roi']}")
    truth = package["ground_truth"]
    with st.expander("发送端 ROI、来源与人工核对记录"):
        st.image(package["roi_preview"], caption="发送端标注预览，不作为接收端底图", width="stretch")
        if truth.get("source_page"):
            st.markdown(f"[查看原图来源]({truth['source_page']})")
        st.write(f"作者：{truth.get('author', '见逐图记录')}；许可：{truth.get('license', '见逐图记录')}")
        if truth.get("license_url"):
            st.markdown(f"[许可说明]({truth['license_url']})")
        st.caption("这是公开来源真实照片，尚不是团队现场采集的巡检数据。共享模式固定使用交付 ROI；需要调整时请切换到上传调试。")
        if package["truth_confirmed"]:
            st.success("交付记录已人工确认：" + package["answer_text"])
        else:
            st.warning("尚无人工确认答案；不进入读数正确率统计。")
            if package["answer_text"]:
                st.write("待核对参考文字：" + package["answer_text"])

    backend = team_bridge.backend_metadata()
    config = (image_id, float(rate), json.dumps(package["metadata"], sort_keys=True),
              json.dumps(backend, sort_keys=True))
    if st.button("生成 A / B / C 对照", type="primary", key="shared_generate"):
        st.session_state.pop("shared_run", None)
        try:
            paths = {"A": package["manifest_a"], "B": package["manifest_bc"], "C": package["manifest_bc"]}
            results = {mode: team_bridge.simulate(path, float(rate), mode) for mode, path in paths.items()}
            manifest_bc = team_bridge.load_ui_manifest(paths["B"])
            for mode in ("B", "C"):
                check_bc_result(manifest_bc, results[mode], mode, float(rate))
            a = results["A"]
            if (len(a["events"]) != 1 or a["events"][0]["packet_id"] != "full"
                    or a["total_bytes"] != package["metadata"]["total_bytes_a"]
                    or not math.isclose(a["full_complete_s"], a["total_bytes"] * 8 / (rate * 1_000_000))
                    or a["roi_complete_s"] != a["full_complete_s"]):
                raise ValueError("A 组整图时间或字节数与图片包不一致。")
            if (results["B"]["total_bytes"] != results["C"]["total_bytes"]
                    or results["B"]["full_complete_s"] != results["C"]["full_complete_s"]):
                raise ValueError("B/C 总字节数与整图到齐时间必须相同。")
            csv_files = {mode: events_csv(paths[mode], result, mode, float(rate),
                         f"共享包联调 | {image_id}") for mode, result in results.items()}
            run_id = "abc_" + uuid.uuid4().hex[:12]
            repo = Path(__file__).resolve().parents[1]
            processing = {}
            for mode, path in paths.items():
                metadata = team_bridge.load_ui_manifest(path)
                processing[mode] = {"milliseconds": metadata.get("processing_ms", {}),
                                    "scope": metadata.get("processing_note", "见原始清单"),
                                    "measurement": "交付包生成时的历史测量，本次没有重新编码"}
            record = {
                "run_id": run_id, "stage": "共享图片包接口联调，非正式实验", "image_id": image_id,
                "rate_mbps": rate, "roi": package["roi"], "source_metadata": package["metadata"],
                "ground_truth": package["answer_text"] if package["truth_confirmed"] else None,
                "ground_truth_status": package["truth_status"], "ground_truth_record": truth,
                "manifest_paths": {mode: Path(path).relative_to(repo).as_posix() for mode, path in paths.items()},
                "backend_metadata": backend, "model": "JPEG载荷串行、固定有效速率、无丢包、无协议开销",
                "results": results, "image_processing": processing,
            }
            record_bytes = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
            logs = runtime_root / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            for mode, payload in csv_files.items():
                (logs / f"{run_id}_{mode}.csv").write_bytes(payload)
            (logs / f"{run_id}_record.json").write_bytes(record_bytes)
            st.session_state.shared_run = {"config": config, "run_id": run_id, "paths": paths,
                                           "results": results, "csv": csv_files, "record": record_bytes}
            st.session_state.shared_time = 0.0
        except (ValueError, OSError, KeyError, ImportError) as error:
            st.error(f"本次对照未生成：{error}")

    run = st.session_state.get("shared_run")
    if run is None or run["config"] != config:
        st.info("选择照片和速率后，点击“生成 A / B / C 对照”。改变参数后需重新生成时间表，JPEG 保持原样。")
        return
    results = run["results"]
    end = max(result["full_complete_s"] for result in results.values())
    st.subheader("同一时刻的接收画面")
    shortcuts = [
        ("开始", "zero", 0.0),
        ("缩略图到齐", "thumb", results["C"]["events"][0]["arrival_s"]),
        ("C 重点到齐", "roi", results["C"]["roi_complete_s"]),
        ("A 整图到齐", "a", results["A"]["full_complete_s"]),
        ("全部到齐", "full", end),
    ]
    for column, (label, key, moment) in zip(st.columns(5), shortcuts):
        if column.button(label, key="shared_time_" + key):
            st.session_state.shared_time = float(moment)
    moment = st.slider("共同模拟时间（秒）", 0.0, float(end), step=float(end) / 500,
                       format="%.5f", key="shared_time")
    show_roi = st.checkbox("同时放大接收端 ROI", key="shared_show_roi")
    st.caption("A 收齐才显示整图；B/C 收齐一个 JPEG 才更新该区域。已收字节只统计完整到达的文件。")
    try:
        receiver_stats = {}
        labels = {"A": "A · 整图传输", "B": "B · 普通顺序", "C": "C · 重点优先"}
        for mode, column in zip(("A", "B", "C"), st.columns(3)):
            with column:
                st.markdown("**" + labels[mode] + "**")
                restored, stats = render_received(run["paths"][mode], results[mode]["events"], float(moment))
                receiver_stats[mode] = stats
                st.image(restored, width="stretch")
                if show_roi:
                    st.image(restored.crop(tuple(package["roi"])), caption="接收端 ROI", width="stretch")
                st.write("重点区域：" + ("已完整到达" if stats["roi_complete"] else "尚未完整到达"))
                total = 1 if mode == "A" else 16
                st.caption(f"已收整图/块 {stats['tiles_received']}/{total} · JPEG {stats['received_bytes']:,} 字节 · 本次恢复 {stats['decode_ms']:.2f} ms")
        # 仅保存最新一次画面恢复的测量；不是整个传输过程的累计解码时间。
        record = json.loads(run["record"])
        record["last_receiver_snapshot"] = {"simulation_time_s": float(moment), "groups": receiver_stats,
            "scope": "最新一次画面恢复的解码/缩放/拼接耗时；重复拖动会更新，不是累计端到端时延"}
        run["record"] = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
        (runtime_root / "logs" / f"{run['run_id']}_record.json").write_bytes(run["record"])
    except (ValueError, OSError) as error:
        st.error(f"接收画面恢复失败：{error}")
        return

    st.subheader("本次时间表与记录")
    st.table([{"组别": mode, "重点到齐（秒）": f"{result['roi_complete_s']:.6f}",
               "整图到齐（秒）": f"{result['full_complete_s']:.6f}", "JPEG 字节数": result["total_bytes"]}
              for mode, result in results.items()])
    st.caption("B/C 用相同字节隔离发送顺序的影响；A 独立编码，字节数可不同。ROI 到齐不代表读数正确，零收益样本也应保留。")
    for mode, column in zip(("A", "B", "C"), st.columns(3)):
        column.download_button(f"下载 {mode} 组时间表", run["csv"][mode],
                               f"{run['run_id']}_{mode}.csv", mime="text/csv", key="shared_download_" + mode)
    st.download_button("下载本次参数记录", run["record"], f"{run['run_id']}_record.json",
                       mime="application/json", key="shared_download_record")
    st.caption("已自动保存到 ui/logs；共享图片包不会被写入。当前没有自动识别、动态画质或真实网络收发。")
    with st.expander("图片处理耗时与统计范围"):
        for mode in ("A", "B"):
            manifest = team_bridge.load_ui_manifest(run["paths"][mode])
            st.write(f"{mode} 组交付包记录的图像处理总耗时（毫秒）：", manifest.get("processing_ms", {}))
            st.caption(manifest.get("processing_note", "见原始清单计时范围。"))
        st.write("这是生成交付包时的历史耗时。本次仅复用 JPEG；界面恢复耗时是单次解码与拼接耗时，均不包含在模拟传输时间中。参数记录保存最新一次画面恢复的耗时与时刻，拖动时间轴会更新该快照。")
