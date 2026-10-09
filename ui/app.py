"""石韵涵的界面模块：上传、ROI 预设、接收恢复与 B/C 对照。

每次调整控件，Streamlit 都会重新执行本文件；session_state 保存当前图片
和已经生成的清单，避免拖动时间滑块时再次切图、编码。
"""

import hashlib
import io
import json
import math
import os
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image

import demo_backend
import team_bridge
from sample_data import load_sample_catalog, read_sample
from ui_support import (
    draw_roi_preview,
    events_csv,
    load_normalized_image,
    load_presets,
    matching_preset,
    render_received,
    save_preset,
)

# 默认把运行数据放在ui目录；自动检查可指定临时目录，避免混入个人实验记录。
ROOT = Path(os.environ.get("ROI_TRANSFER_WORKSPACE", Path(__file__).resolve().parent)).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
PRESETS = ROOT / "data" / "roi_presets.json"


def demo_bytes() -> bytes:
    """将内置测试图放进内存，和上传照片使用同一套界面流程。"""
    output = io.BytesIO()
    demo_backend.create_demo_image().save(output, format="PNG")
    return output.getvalue()


def check_result(manifest: dict, result: dict, mode: str, rate: float) -> None:
    """接入队友模块时也检查关键约定，防止界面显示不公平的比较。"""
    packets = manifest["packets"]
    by_id = {packet["packet_id"]: packet for packet in packets}
    expected_ids = {"thumb"} | {f"tile_{i:02d}" for i in range(16)}
    if len(packets) != 17 or set(by_id) != expected_ids:
        raise ValueError("图片清单必须包含一个 thumb 和 tile_00 至 tile_15。")
    if not any(packet["priority"] == 1 for packet in packets):
        raise ValueError("清单里没有重点块，请检查 ROI。")
    order = sorted(packets, key=lambda p: (p["packet_id"] != "thumb", p["packet_id"]))
    if mode == "C":
        order = sorted(packets, key=lambda p: (p["priority"], p["packet_id"]))
    events = result["events"]
    if [event["packet_id"] for event in events] != [p["packet_id"] for p in order]:
        raise ValueError(f"{mode} 组发送顺序不符合共同约定。")
    cumulative = 0
    previous = 0.0
    for event in events:
        cumulative += by_id[event["packet_id"]]["nbytes"]
        expected = cumulative * 8 / (rate * 1_000_000)
        if event["cumulative_bytes"] != cumulative:
            raise ValueError("累计字节数与清单不一致。")
        if not math.isclose(event["start_s"], previous, abs_tol=1e-10):
            raise ValueError("图片块开始时刻不连续。")
        if not math.isclose(event["arrival_s"], expected, abs_tol=1e-10):
            raise ValueError("到达时间不符合固定有效速率模型。")
        previous = expected
    expected_roi = max(e["arrival_s"] for e in events if by_id[e["packet_id"]]["priority"] == 1)
    if result["total_bytes"] != cumulative:
        raise ValueError("传输总字节数不一致。")
    if not math.isclose(result["full_complete_s"], previous, abs_tol=1e-10):
        raise ValueError("整图完成时刻不一致。")
    if not math.isclose(result["roi_complete_s"], expected_roi, abs_tol=1e-10):
        raise ValueError("重点区域完成时刻不一致。")


# 1. 页面入口：测试模块与队友模块明确区分。
st.set_page_config(page_title="巡检图片优先传输", page_icon="📷", layout="wide")
st.title("巡检图片重要区域优先传输")
st.caption("石韵涵 · 界面与接收端 · B/C联合调试")
try:
    catalog = load_sample_catalog(ROOT)
    catalog_error = None
except (ValueError, OSError) as error:
    catalog = {"dataset": {}, "samples": []}
    catalog_error = str(error)
with st.sidebar:
    st.header("本次设置")
    backend_name = st.radio("运行模块", ["队友正式模块（软件仿真）", "内置接口测试模块"], key="backend")
    sources = ["内置测试图", "上传巡检照片", "从 images 文件夹选择"]
    if catalog["samples"]:
        sources.insert(0, "公开仪表样本")
    source = st.radio("图片来源", sources, key="source")
    if catalog_error:
        st.error("公开样本清单无法读取：" + catalog_error)
    rate = st.selectbox("有效传输速率（Mbps）", [0.25, 1.0, 5.0], key="rate")
    st.caption("固定有效速率、无丢包；这是应用层传输模拟，不代表完整 5G 链路。")

prepare = demo_backend.prepare_image
simulate = demo_backend.simulate
if backend_name == "队友正式模块（软件仿真）":
    try:
        backend_metadata = team_bridge.backend_metadata()
        prepare = team_bridge.prepare_image
        simulate = team_bridge.simulate
    except (ImportError, AttributeError, OSError) as error:
        st.error(f"队友模块暂时无法接入：{error}")
        st.stop()
    st.info("已接入队友的图像处理和传输计时模块。当前为固定有效速率的软件仿真；更换模块文件后请重启应用。")
else:
    backend_metadata = {"backend": "demo_backend", "purpose": "接口功能测试"}
    st.info("界面联调模式：使用独立的接口测试模块。此处生成的图像和日志用于检查功能，不能当作正式巡检实验结果。")

# 2. 获取图片。所有照片只在本机处理，原始上传内容单独保存。
image_bytes = None
source_name = "interface_test.png"
sample = None
if source == "内置测试图":
    if "demo_bytes" not in st.session_state:
        st.session_state.demo_bytes = demo_bytes()
    image_bytes = st.session_state.demo_bytes
    st.caption("这张图由程序生成，仪表文字仅用于接口测试，没有真实巡检含义。")
elif source == "上传巡检照片":
    uploaded = st.file_uploader("选择一张 JPG、PNG 或 WebP 图片", type=["jpg", "jpeg", "png", "webp"])
    if uploaded is not None:
        image_bytes, source_name = uploaded.getvalue(), uploaded.name
elif source == "公开仪表样本":
    samples = {item["sample_id"]: item for item in catalog["samples"]}
    sample_id = st.selectbox("选择真实仪表照片", list(samples),
                             format_func=lambda value: f"{value} · {samples[value]['source_filename']}",
                             key="sample_id")
    sample = samples[sample_id]
    try:
        image_bytes, _ = read_sample(ROOT, sample)
    except (ValueError, OSError) as error:
        st.error(f"样本读取失败：{error}")
        st.stop()
    source_name = sample["source_filename"]
    dataset = catalog["dataset"]
    st.markdown(f"真实图片来源：[{dataset['name']}]({dataset['url']}) · 许可：{dataset['license']}")
    st.caption("这些照片用于功能调试；逐图载入保存的ROI，不是模型自动检测，也不是同一设备的固定视角序列。")
    if sample.get("note"):
        st.caption(sample["note"])
else:
    available = sorted(p for p in (ROOT / "images").glob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if available:
        selected_name = st.selectbox("照片文件", [p.name for p in available])
        selected_path = ROOT / "images" / selected_name
        image_bytes, source_name = selected_path.read_bytes(), selected_name
    else:
        st.info("images 文件夹还没有照片。可切换为上传巡检照片，或先使用内置测试图。")
if image_bytes is None:
    st.info("先选择一张图片，再设置重点区域。")
    st.stop()
photo_hash = hashlib.sha256(image_bytes).hexdigest()
try:
    if st.session_state.get("loaded_hash") != photo_hash:
        st.session_state.loaded_image = load_normalized_image(image_bytes)
        st.session_state.loaded_hash = photo_hash
    image = st.session_state.loaded_image
    width, height = image.size
    if min(width, height) < 4:
        raise ValueError("图片宽高都至少需要 4 个像素。")
except Exception as error:
    st.error(f"无法读取这张图片：{error}")
    st.stop()

# 换照片时清空上张照片的读数确认；样本读数只是参考，不能自动成为真值。
source_identity = (source, sample["sample_id"] if sample else source_name, photo_hash)
reading_context = source_identity
if st.session_state.get("reading_context") != reading_context:
    st.session_state.truth = sample["reference_reading"] if sample else ""
    st.session_state.truth_checked = False
    if sample:
        st.session_state.device_id = sample["sample_id"]
    st.session_state.reading_context = reading_context
with st.sidebar:
    if "device_id" not in st.session_state:
        st.session_state.device_id = "device_001"
    device_id = st.text_input("设备编号", key="device_id").strip()
    truth = st.text_input("参考读数或状态（可留空）", placeholder="例如：12.6 V；绿色灯亮", key="truth")
    truth_context = (source_identity, truth)
    if st.session_state.get("truth_context") != truth_context:
        st.session_state.truth_checked = False
        st.session_state.truth_context = truth_context
    truth_checked = st.checkbox("我已人工核对本图读数或状态", key="truth_checked", disabled=not bool(truth.strip()))
    st.caption("没有确认的文字仅作参考，不记为实验正确答案。")
if not device_id:
    st.warning("请在左侧填写设备编号，用来保存和复用 ROI。")
    st.stop()

# 3. 按设备和图像尺寸复用 ROI；坐标改变后立即重新画预览框。
presets = {}
preset_error = None
try:
    presets = load_presets(PRESETS)
    preset_roi = matching_preset(presets, device_id, width, height)
except (ValueError, OSError) as error:
    preset_roi = None
    preset_error = str(error)
context = (source_identity, device_id)
if st.session_state.get("roi_context") != context:
    default_roi = preset_roi or (sample["roi"] if sample else None) or (int(width * 0.60), int(height * 0.55), max(int(width * 0.94), int(width * 0.60) + 1), max(int(height * 0.88), int(height * 0.55) + 1))
    for key, value in zip(("x0", "y0", "x1", "y1"), default_roi):
        st.session_state[key] = value
    st.session_state.roi_context = context

st.subheader("1 · 设置重点区域")
preview_column, controls = st.columns([3, 2])
with controls:
    st.write(f"图片尺寸：{width} × {height} 像素")
    st.caption("红框内是 ROI。x 向右增大，y 向下增大；黄色网格表示 16 个图片块。")
    left, right = st.columns(2)
    with left:
        x0 = st.number_input("左边 x0", min_value=0, max_value=width - 1, step=1, key="x0")
        y0 = st.number_input("上边 y0", min_value=0, max_value=height - 1, step=1, key="y0")
    with right:
        x1 = st.number_input("右边 x1", min_value=1, max_value=width, step=1, key="x1")
        y1 = st.number_input("下边 y1", min_value=1, max_value=height, step=1, key="y1")
    roi = (int(x0), int(y0), int(x1), int(y1))
    valid_roi = x0 < x1 and y0 < y1
    if not valid_roi:
        st.error("右边必须大于左边，下边必须大于上边。")
    if preset_error:
        st.error("ROI 配置读取失败，已有文件不会被覆盖：" + preset_error)
    elif preset_roi:
        st.caption("该设备已有匹配尺寸的 ROI 预设；切换到同设备照片时会自动载入。")
    elif sample and sample["roi"]:
        st.caption("已载入该照片的ROI。来源：" + sample["roi_origin"] + "。请核对红框是否覆盖完整显示窗口。")
    else:
        st.caption("当前未匹配到同尺寸的设备预设，请检查红框后保存。")
    if st.button("保存此设备 ROI", disabled=not valid_roi or bool(preset_error), key="save_roi"):
        try:
            save_preset(PRESETS, device_id, width, height, roi)
            st.success("设备 ROI 已保存。后续照片仍需保持拍摄位置与视角一致。")
        except (ValueError, OSError) as error:
            st.error(f"保存失败：{error}")
    st.caption("尺寸相同不保证角度相同，每次都请看红框是否仍覆盖仪表或状态区域。")
with preview_column:
    preview = draw_roi_preview(image, roi) if valid_roi else image
    st.image(preview, caption="发送端预览 · 此图不作为接收端底图", width="stretch")
    if valid_roi:
        with st.expander("放大查看发送端 ROI，核对读数"):
            st.image(image.crop(roi), caption="原图局部，仅供准备参考答案；不是接收端画面。", width="stretch")

# 4. 按按钮才生成清单。B/C 共用清单，调整速率可以复用 JPEG。
# 模块源码变更也视为新配置，防止旧图片包被记到新模块版本名下。
backend_identity = json.dumps(backend_metadata, sort_keys=True)
config = (source_identity, roi, backend_name, backend_identity, rate, device_id, truth, truth_checked)
bundle_key = (photo_hash, roi, backend_name, backend_identity)
if st.button("生成 B / C 对照", type="primary", disabled=not valid_roi, key="generate"):
    try:
        with st.spinner("准备图片块并计算到达时间…"):
            cache = st.session_state.setdefault("bundle_cache", {})
            if bundle_key not in cache:
                input_dir = ROOT / "data" / "ui_inputs"
                input_dir.mkdir(parents=True, exist_ok=True)
                input_file = input_dir / f"{photo_hash}.image"
                if not input_file.exists():
                    input_file.write_bytes(image_bytes)
                output_dir = ROOT / "data" / "ui_runs" / (photo_hash[:10] + "_" + uuid.uuid4().hex[:8])
                manifest_path = str(prepare(str(input_file), roi, str(output_dir)))
                cache[bundle_key] = manifest_path
            manifest_path = cache[bundle_key]
            manifest = team_bridge.load_ui_manifest(manifest_path)
            if (manifest["width"], manifest["height"], tuple(manifest["roi"])) != (width, height, roi):
                raise ValueError("图像模块返回的图片尺寸或 ROI 与界面设置不一致。")
            results = {mode: simulate(manifest_path, float(rate), mode) for mode in ("B", "C")}
            for mode in ("B", "C"):
                check_result(manifest, results[mode], mode, float(rate))
            if results["B"]["total_bytes"] != results["C"]["total_bytes"] or not math.isclose(results["B"]["full_complete_s"], results["C"]["full_complete_s"], abs_tol=1e-10):
                raise ValueError("B/C必须使用同一批JPEG，字节数和整图完成时间须相同。")
            source_label = f"接口联调 | {backend_name} | {source} | {source_name}"
            csv_files = {mode: events_csv(manifest_path, results[mode], mode, float(rate), source_label) for mode in ("B", "C")}
            run_id = "ui_" + uuid.uuid4().hex[:12]
            log_dir = ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            for mode in ("B", "C"):
                (log_dir / f"{run_id}_{mode}.csv").write_bytes(csv_files[mode])
            record = {"run_id": run_id, "stage": "接口联调，非正式实验", "source": source_label, "source_filename": source_name, "image_sha256": photo_hash, "device_id": device_id, "reference_reading": truth, "ground_truth": truth if truth_checked else None, "ground_truth_status": "用户已核对" if truth_checked else "待人工核对", "roi": list(roi), "rate_mbps": rate, "manifest_path": Path(manifest_path).relative_to(ROOT).as_posix(), "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(), "backend_metadata": backend_metadata, "model": "JPEG载荷串行、固定有效速率、无丢包、无协议开销", "results": results}
            if sample:
                record["sample_metadata"] = {"dataset": catalog["dataset"], "sample_id": sample["sample_id"], "source_filename": sample["source_filename"], "original_roi": sample["roi"], "roi_origin": sample["roi_origin"], "roi_changed": list(roi) != sample["roi"], "original_reference_reading": sample["reference_reading"], "original_reading_status": sample["reading_status"]}
            (log_dir / f"{run_id}_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            st.session_state.run = {"config": config, "manifest_path": manifest_path, "manifest": manifest, "results": results, "csv": csv_files, "run_id": run_id}
            st.session_state.view_time = 0.0
    except Exception as error:
        st.error(f"本次对照未生成：{error}")
        st.session_state.pop("run", None)

run = st.session_state.get("run")
if run is None:
    st.info("确认红框后，点击“生成 B / C 对照”。两边的接收画面会从空白开始。")
    st.stop()
if run["config"] != config:
    st.info("图片或参数已经改变，请重新点击“生成 B / C 对照”。")
    st.stop()

# 5. 共用一条模拟时间轴，接收函数只读取已经完整到达的图片文件。
st.subheader("2 · 在同一时刻比较接收结果")
results = run["results"]
full_time = float(results["B"]["full_complete_s"])
b1, b2, b3, b4 = st.columns(4)
if b1.button("回到开始", key="time_zero"):
    st.session_state.view_time = 0.0
if b2.button("查看缩略图到齐", key="time_thumbnail"):
    st.session_state.view_time = float(results["C"]["events"][0]["arrival_s"])
if b3.button("查看 C 组重点到齐时刻", key="time_roi"):
    st.session_state.view_time = float(results["C"]["roi_complete_s"])
if b4.button("查看全部到齐", key="time_full"):
    st.session_state.view_time = full_time
t = st.slider("共同模拟时间（秒）", min_value=0.0, max_value=full_time, step=full_time / 500, format="%.5f", key="view_time")
st.caption("这是计算得到的模拟时间。拖动快慢不影响结果；已收字节只统计完整到达的 JPEG 文件。")
columns = st.columns(2)
try:
    for mode, column in zip(("B", "C"), columns):
        with column:
            st.markdown("**" + ("B · 普通顺序" if mode == "B" else "C · 重点优先") + "**")
            restored, stats = render_received(run["manifest_path"], results[mode]["events"], float(t))
            st.image(restored, width="stretch")
            st.write("重点区域：" + ("已完整到达" if stats["roi_complete"] else "尚未完整到达"))
            st.caption(f"完整图片块 {stats['tiles_received']}/16 · 已收 JPEG {stats['received_bytes']:,} 字节 · 本次画面恢复 {stats['decode_ms']:.2f} ms")
except Exception as error:
    st.error(f"接收画面恢复失败：{error}")
    st.stop()

# 6. 保存结果来源，不把内置测试图的数值当成真实巡检结论。
st.subheader("3 · 本次时间表与日志")
st.table([
    {"组别": mode, "重点区域到齐（秒）": f"{results[mode]['roi_complete_s']:.6f}", "整图到齐（秒）": f"{results[mode]['full_complete_s']:.6f}", "JPEG 总字节数": results[mode]["total_bytes"]}
    for mode in ("B", "C")
])
st.caption("同一批 JPEG、相同速率且无丢包，B/C 整图到齐时间相同。ROI 数据到齐不等同于已经正确读出仪表。")
download_b, download_c, download_record = st.columns(3)
download_b.download_button("下载 B 组时间表", data=run["csv"]["B"], file_name=f"{run['run_id']}_B.csv", mime="text/csv")
download_c.download_button("下载 C 组时间表", data=run["csv"]["C"], file_name=f"{run['run_id']}_C.csv", mime="text/csv")
download_record.download_button("下载本次参数记录", data=(ROOT / "logs" / f"{run['run_id']}_record.json").read_bytes(), file_name=f"{run['run_id']}_record.json", mime="application/json")
st.caption("时间表和本次配置也已自动保存到 logs 文件夹，均带有接口联调标识。")
st.caption("尚未接入A组整图基线、自动ROI检测或动态画质；本轮先验证B/C联调。")
with st.expander("查看图片处理耗时和统计范围"):
    st.write(run["manifest"].get("processing_ms", "当前图像模块未提供处理耗时。"))
    if run["manifest"].get("processing_note"):
        st.caption(run["manifest"]["processing_note"])
    st.write("上方处理耗时单位为毫秒，由图像模块实测；接收画面下方为本次恢复耗时，不是累计端到端耗时。")
    st.write("传输只计算缩略图和 16 个 JPEG 文件，不计清单、协议开销或重传。")
