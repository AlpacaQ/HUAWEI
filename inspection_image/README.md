# 图像模块第一版 分阶段运行说明

## GitHub下载后的快速运行

需要Python 3.10或以上。在仓库根目录运行（若电脑使用`py`命令，可将`python`换成`py`）：

```powershell
python -m pip install -r requirements.txt
python make_debug_sample.py
python image_processing.py examples/debug_sample.png --roi 450 310 720 520 --output-dir examples/my_run01
python check_image.py examples/debug_sample.png --manifest examples/my_run01/manifest.json --output-dir examples/my_check01
python -m unittest -v test_image_processing.py
```

成功时生成17个JPEG和清单；检查打印`pre_encoding_pixel_equal: true`，自动测试显示`OK`。输出目录需要为空或尚不存在，重跑时换一个名称。仓库中的示例均为合成调试数据。

下文保留首次开发电脑的本地路径和实测调试记录；在其他电脑上按仓库实际位置替换路径。

 代码所在目录：`C:\Users\28562\Documents\ChatGPT\FPGA\inspection_image`。
本目录独立于现有FPGA工程，没有修改传输模块或界面。设备ROI预设的保存、读取仍由界面负责；本模块只接收已选好的ROI。

## 本版约定

以本次用户要求为准，附件仅提供背景和字段含义。附件的320像素缩略图宽度、85/35质量、说明信息计入传输等旧设定，不用于本版。

- 图片经EXIF朝向校正后转RGB；ROI必须对应这一结果，不对应未旋转的原始文件坐标，也不对应缩放后的屏幕坐标。
- ROI和块的`box`均为`[x0,y0,x1,y1]`，左上包含、右下不包含。只接受整数像素坐标，不静默纠正无效坐标。
- 固定4×4，编号0到15，按行从左到右、从上到下。全部块质量80；缩略图最长边≤256、质量50，均为调试初值，不代表画质百分比。
- 每个传输文件仅编码一次。B、C必须复用同一个输出目录下的17个JPEG。
- 字节统计只有缩略图和16块，清单、检查PNG不计入。没有协议开销、重传、真实网络测试。
- 图片宽高至少各4像素，才能生成16个非空JPEG；更小的图片会报错。

## 文件作用

| 文件 | 作用 |
|---|---|
| image_processing.py | 图片处理函数和可直接运行的命令行入口 |
| check_image.py | 导出处理后图片供选ROI；检查清单并生成标注、拼接图 |
| requirements.txt | Python依赖，只有Pillow |
| make_debug_sample.py | 生成一张803×607的合成调试图，不是现场数据 |
| test_image_processing.py | 非整除尺寸、ROI、EXIF、颜色转换等正确性测试 |
| examples/debug_sample.png | 已生成的单图调试输入 |
| examples/run01/ | 已生成的17个JPEG和清单 |
| examples/check01/ | 已生成的人工检查图片和检查报告 |

## 阶段一 环境和处理后图片

在PowerShell进入上述代码目录。当前电脑没有可直接执行的`python`命令，本次已使用Codex自带的Python跑通，以下命令可直接在这台电脑使用：

```powershell
Set-Location 'C:\Users\28562\Documents\ChatGPT\FPGA\inspection_image'
$imagePython = 'C:\Users\28562\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $imagePython -c "import PIL; print(PIL.__version__)"
```

成功应输出Pillow版本号。如果你使用自己安装的Python，可以将`$imagePython`改为它的完整路径；缺少依赖时执行：

```powershell
& $imagePython -m pip install -r requirements.txt
```

当前自带环境已经包含Pillow，不需要安装。

先使用本目录现有的合成图片。也可运行以下命令重新生成同一调试输入：

```powershell
& $imagePython make_debug_sample.py
& $imagePython check_image.py examples/debug_sample.png --export-processed examples/processed_for_roi.png
```

成功应输出`803×607`、`RGB`，并生成`processed_for_roi.png`。用图片查看器打开它，确定ROI。示例白色读数框采用`[450,310,720,520]`，对应270×210像素。选区的实际可见最后一列是719、最后一行是519。

换成自己的照片时，先运行同样的`--export-processed`命令，例如：

```powershell
& $imagePython check_image.py 'D:\photos\device.jpg' --export-processed examples/device_processed.png
```

请将示例路径换成实际存在的文件；先查看输出PNG，再确定其中的像素ROI。没有用户现场照片，本次不把合成图冒充巡检照片。

## 阶段二 分块并生成清单

```powershell
& $imagePython image_processing.py examples/debug_sample.png --roi 450 310 720 520 --output-dir examples/run02
```

本次已经生成`run01`，因此给你重跑时使用`run02`。输出目录必须为空或不存在；再次运行请换成`run03`等新目录，避免覆盖已有实验输入。

成功应打印`manifest.json`的绝对路径；输出目录有18个文件：`thumbnail.jpg`、`tile_00.jpg`至`tile_15.jpg`和`manifest.json`。缩略图为256×194像素。所有JPEG都是正常朝向、RGB，不携带原始EXIF旋转信息。

函数调用保持用户指定形式：

```python
from image_processing import prepare_image

manifest_path = prepare_image(
    "examples/debug_sample.png",
    [450, 310, 720, 520],
    "examples/run03",
)
print(manifest_path)  # 字符串形式的清单绝对路径
```

调用脚本应放在本目录，或由调用方正常配置Python导入路径。函数不弹出界面、不保存设备ROI预设、不执行传输。

## 阶段三 拼接验收和人工检查

```powershell
& $imagePython check_image.py examples/debug_sample.png --manifest examples/run02/manifest.json --output-dir examples/check02
```

成功应打印`pre_encoding_pixel_equal: true`，并生成：

| 输出 | 该看什么 |
|---|---|
| processed.png | 校正朝向后的RGB基准图 |
| roi_tiles.png | 黄色ROI边框、红色重点块边框、青色背景块边框、块编号 |
| reassembled_before_encoding.png | 内存裁剪再拼接，像素必须与processed.png完全一致 |
| reassembled_after_jpeg.png | 解码已有16个JPEG后拼接，可能有压缩痕迹，保存PNG以免再次有损编码 |
| check_report.json | 像素验收、JPEG是否像素一致、真实字节数及原处理耗时 |

本例重点块应为10、11、14、15。仅接触ROI边缘的块不算重点。标注只画在检查副本上，不写入传输图片。

验收依据是**JPEG编码前**的像素一致性。`jpeg_pixel_equal: false`不能证明裁剪错误；它说明JPEG解码后像素发生变化。本脚本同时检查16块的编号、坐标、尺寸、模式、重点标记和实际文件长度。检查时必须使用生成清单时的同一张原图；本版不包含输入内容指纹校验。

自动正确性测试命令：

```powershell
& $imagePython -m unittest -v test_image_processing.py
```

应显示4项测试`ok`，最后`OK`。这些是合成输入的软件测试，不是真实巡检实验。

## image_processing.py 各段代码

1. 导入与常量：Pillow负责读图、朝向、裁剪和编码；Path负责文件路径和实际长度；json写清单；perf_counter测本机实际耗时。三项质量/尺寸初值集中在顶部。
2. `load_processed_image`：使用上下文管理及时关闭输入文件，`exif_transpose`校正朝向，`convert("RGB")`统一颜色模式。清除元信息，防止输出被再次旋转。它不会保存JPEG。
3. `validate_roi`：检查四个整数、非空矩形和图片内边界；bool虽然在Python中属于整数的子类，也会被拒绝。报错尺寸是处理后的尺寸。
4. `tile_boxes`：横向边界为`i*width//4`，纵向为`i*height//4`，i取0至4。相邻块共用边界，最后边界恰好等于宽高。803像素的横向边界是0、200、401、602、803；不会丢失右边余数。两层循环先行后列。
5. `intersects`：两个方向的交叠长度都必须大于0；使用严格小于排除边缘接触。
6. `prepare_image`前半段：计时、读图、校验，创建空输出目录；复制原图缩小，再只保存一次缩略JPEG；读取落盘后的真实大小。
7. `prepare_image`循环：按半开区间裁剪，每块保存一次JPEG，再记录位置、大小、重点标记、质量和文件实际字节数。原图本身不额外编码为整图JPEG。
8. `prepare_image`后半段：汇总清单和17个文件的总长度，停止处理计时，然后写JSON并返回路径。
9. `main`及末尾判断：通过argparse接收命令行参数；输入/文件错误输出明确失败信息。被其他模块导入时不会自动执行命令行程序。

RGB转换不等于专业色彩管理；本版没有额外ICC色彩校正。RGBA按Pillow的`convert("RGB")`去除alpha，不自行引入透明背景合成规则。

## check_image.py 各段代码

1. 导入公共函数：复用同一朝向、坐标和相交规则，避免检查端另写一套规则造成不一致。
2. `export_processed`：输出无损PNG作为选ROI的基准；不生成传输JPEG。
3. `check_image`初始化：读取原图与清单，验证处理后尺寸、RGB、ROI和块数，创建两个空画布及标注副本。
4. 检查循环前半段：清单坐标对照应有边界，裁剪处理后RGB原图并粘回`before`，检查实际字节数。
5. 检查循环后半段：打开已有JPEG并检查尺寸、颜色模式，然后放回`after`；绘制不同颜色的块框和编号。不会重新调用JPEG编码。
6. 循环后：验证总长度，用ImageChops计算编码前逐像素差值；存在非零差值立即报错。另画ROI框，保存PNG和检查JSON。
7. 命令行入口：`--export-processed`和`--manifest`二选一；方便先选ROI、再验收已生成的结果。

`make_debug_sample.py`的main依次创建非整除尺寸画布、写入彩色像素和模拟读数框、标明合成数据、保存PNG。`test_image_processing.py`用临时目录避免覆盖已有输出，覆盖非整除尺寸恢复、字节汇总、边缘接触、无效ROI、小图拒绝、EXIF旋转及灰度/调色板/RGBA转RGB。

## 清单格式与其他同学的交接

附件没有给出完整JSON模板或既有接口代码；以下是本模块第一版明确的清单结构，未修改其他同学的接口。`payload`在JSON中使用相对文件名表示文件内容入口，不能直接放Python bytes。消费者通过`清单所在目录 / payload`读取字节；发送前不应再次编码。

| 字段 | 含义 |
|---|---|
| schema_version | 当前为1 |
| image_id | 输出目录名；调用方应为不同图片安排不同目录名 |
| source_name | 输入文件名，便于人工追溯 |
| width、height、mode | EXIF校正后尺寸和RGB模式 |
| roi | 处理后的图片像素坐标 |
| coordinate_convention | 半开区间说明 |
| grid | rows=4、cols=4 |
| thumbnail | image_id、payload、size_bytes、width、height、quality |
| tiles | 按tile_id升序排列的16个块记录 |
| total_size_bytes | thumbnail和16块实际字节数总和，不含清单 |
| image_processing_seconds | 本次本机图片处理实测秒数 |
| processing_time_scope | 计时边界说明 |

块记录示例（size_bytes请以实际清单为准）：

```json
{
  "image_id": "run01",
  "tile_id": 10,
  "box": [401, 303, 602, 455],
  "x": 401,
  "y": 303,
  "w": 201,
  "h": 152,
  "priority": 1,
  "quality": 80,
  "payload": "tile_10.jpg",
  "size_bytes": 0
}
```

这里的0仅是字段格式占位，不是实测文件大小。`x,y,w,h`保留附件字段；`box`提供用户统一坐标，两者严格一致。priority=1表示重点，0表示背景，不能按priority升序发送。

供传输同学理解的队列规则，不在本模块执行：

```python
tiles = manifest["tiles"]
b_tiles = sorted(tiles, key=lambda tile: tile["tile_id"])
c_tiles = sorted(tiles, key=lambda tile: (-tile["priority"], tile["tile_id"]))
b_queue = [manifest["thumbnail"]] + b_tiles
c_queue = [manifest["thumbnail"]] + c_tiles
```

本例B：缩略图、0至15。C：缩略图、10、11、14、15、0、1、2、3、4、5、6、7、8、9、12、13。两者文件与总长度完全相同。

传输同学采用固定有效速率0.25、1、5 Mbps，无丢包；Mbps按十进制，`字节/秒 = Mbps × 1_000_000 / 8`，文件模拟发送耗时为`size_bytes × 8 / (Mbps × 1_000_000)`。本模块没有生成或记录模拟传输时间。附件100ms单向延迟未在本次请求中明确保留，本模块不自行设置；如传输同学使用延迟，应独立于有效带宽处理。

`image_processing_seconds`从进入prepare_image开始，包含读图、朝向转换、RGB转换、裁剪、缩略图缩放、JPEG编码及落盘、文件长度读取和清单数据构造；在写manifest前停止。JSON序列化和落盘明确不包含在这个字段内。检查脚本解码、PNG导出、人工选区、界面刷新、播放等待和模拟传输都不计入它。需要其他时间时，应由对应模块另记字段。

## 本次单图运行记录

合成输入803×607，ROI `[450,310,720,520]`；17个JPEG共51,809字节；编码前像素一致为true，JPEG解码后像素一致为false。处理耗时约0.179秒，仅是本次这台电脑的一次调试测量，重跑会变化。4项正确性测试通过。

下一步应替换为一张自己拍摄的设备照片，先导出处理后PNG确定ROI，再重复阶段二、三。保存正确读数及人工判断时另记真实记录；目前不能据此声称重点传输缩短了多少时间或提升了读数正确率。
