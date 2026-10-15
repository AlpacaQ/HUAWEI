# 巡检图片重要区域优先传输系统

三人联合软件原型：图像包（邱雪瑶）→ 发送排序和计时（朱雨萱）→ 同时刻接收恢复与日志（石韵涵）。当前已接入共享图片包的 **A/B/C 对照**，并保留上传照片和设备 ROI 预设的 B/C 调试入口。

## 从这里开始

下载完整仓库，在根目录打开终端。第一次执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ui/requirements.txt
.\.venv\Scripts\python.exe start_ui.py
```

如果只有 `py` 命令，第一行改成 `py -3 -m venv .venv`。以后只运行最后一行。详细操作、文件作用、共同字段和测试方法见 [界面运行说明](ui/README.md)。

打开后保持“共享图片包 A/B/C”，选择 meter01 和 0.25 Mbps，点击“生成 A / B / C 对照”，再点击“C 重点到齐”。A 收齐整图才显示；B 普通顺序补块；C 重点优先补块。三组共用同一时间轴。日志自动保存在 `ui/logs`，也能下载。

## 共同图片包

- [B/C 五图包](inspection_image/delivery_v2)：每图缩略图加 16 块，共 85 个 JPEG，4,123,492 字节。[ZIP](inspection_image/inspection_image_delivery_v2_5images.zip) · [SHA256](inspection_image/inspection_image_delivery_v2_5images.zip.sha256) · [接口说明](inspection_image/delivery_v2/共同接口说明.md)。原清单 `priority=1` 为重点、`0` 为背景。
- [A 整图包](inspection_image/delivery_A_v1)：五个质量 80 的整图 JPEG，共 4,036,569 字节。[ZIP](inspection_image/inspection_image_delivery_A_v1.zip) · [SHA256](inspection_image/inspection_image_delivery_A_v1.zip.sha256) · [编码与验收说明](inspection_image/README_A.md)。

界面直接读取这两份包，检查图片对应关系、文件大小和 SHA256，不重新编码，也不往交付包写入适配清单。B/C 使用完全相同的 JPEG；A 独立编码，字节数允许不同。照片来源与许可保存在每张图的 ground_truth.json 中。

meter01 的交付记录已人工确认 3.23 V（直流）；meter03、meter05 仍待人工确认，meter02、meter04 没有可确认答案。界面不会把待确认参考文字计为正确答案。

## 验证与当前边界

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s ui -p "test_*.py" -v
.\.venv\Scripts\python.exe transmission_starter/check_transmission.py
```

检查内容与实际执行记录见 [集成验收记录](ui/INTEGRATION_VALIDATION.md)。图片处理模块及独立验收见 [图像模块说明](inspection_image/README.md)，传输接口见 [传输模块说明](transmission_starter/README.md)。

当前模型为 JPEG 载荷串行、固定有效速率、无丢包，不计协议头、重传和传播时延；尚未实现真实 Wi-Fi/5G 收发、自动 ROI 检测或动态画质。到达时间是模型计算结果，编码/解码耗时是相应阶段的本机测量。ROI 到齐不等于读数正确，仍需人工读数实验；不能把软件验收当成正式竞赛性能结论。
