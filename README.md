# 巡检图片重要区域优先传输系统

## 三人联合界面

石韵涵的界面位于 [ui](ui/README.md)，接入本仓库的图像和传输模块，支持上传照片、保存ROI、B/C同时间恢复对照和日志下载。完整启动与逐文件说明见界面README。

在已安装依赖的Python环境中，从仓库根目录运行：

```powershell
python -m pip install -r ui/requirements.txt
python start_ui.py
```

当前为固定有效速率的B/C软件联调，不是实测5G网络；A组、自动检测和动态画质尚未接入。界面通过集中字段适配连接两个现有模块，不修改或重复压缩B/C的JPEG文件。

## 图像模块单独运行

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
