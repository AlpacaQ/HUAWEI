# 巡检图片重要区域优先传输系统

## A组整图传输

直接下载 [A组整图包](inspection_image/inspection_image_delivery_A_v1.zip)，对照 [SHA256](inspection_image/inspection_image_delivery_A_v1.zip.sha256)。5张原图分别编码成质量80的完整JPEG，与B/C的朝向和尺寸一致；5个full.jpg合计4,036,569字节，队友无需重新压缩。

[A组目录与清单](inspection_image/delivery_A_v1)独立于B/C图片包，详见 [运行和接口说明](inspection_image/README_A.md)。从仓库根目录先进入inspection_image，再验收：

```powershell
Set-Location inspection_image
python image_processing_A.py --bc-package delivery_v2 --output-dir delivery_A_v1 --verify-only
```

## 五张真实仪表图片包

朱雨萱和石韵涵请下载同一份 [五图交付ZIP](inspection_image/inspection_image_delivery_v2_5images.zip)（点击文件页的下载按钮），并对照 [SHA256](inspection_image/inspection_image_delivery_v2_5images.zip.sha256)。包内每张17个传输JPEG，5张共85个，合计4,123,492字节，无需重新压缩。

也可直接浏览 [图片包目录](inspection_image/delivery_v2)、[共同接口说明](inspection_image/delivery_v2/共同接口说明.md)和[逐图记录](inspection_image/delivery_v2/图片记录.csv)。priority=1为重点、0为背景。meter02与meter04按用户反馈保留null答案；meter03与meter05为视觉核对、人工确认待完成。人工已确认的meter01读数为3.23 V（直流）。这些照片来自公开来源，每张附来源和许可。

从仓库根目录验收：

```powershell
Set-Location inspection_image
python verify_package.py delivery_v2
```

图像模块位于 [`inspection_image`](inspection_image/README.md)。包含正常朝向及RGB转换、ROI校验、4×4 JPEG分块、清单生成和人工检查工具。

```powershell
cd inspection_image
python -m pip install -r requirements.txt
python make_debug_sample.py
python image_processing.py examples/debug_sample.png --roi 450 310 720 520 --output-dir examples/my_run01
python check_image.py examples/debug_sample.png --manifest examples/my_run01/manifest.json --output-dir examples/my_check01
python -m unittest -v test_image_processing.py
```

示例图片和记录均为合成数据的软件调试结果，不是真实巡检或网络实验。详细约定和分阶段说明见模块README。
