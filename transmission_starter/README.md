# 巡检图片 A/B/C 发送顺序与弱网计时模块

本模块直接读取邱雪瑶交付的分块图片包和 A 组整图包，检查真实文件字节数，计算固定有效速率下的串行到达时间，并可导出 CSV。读取图片包时不会重新编码图片、修改清单或创建中间清单。代码只使用 Python 标准库，建议 Python 3.11 或更新版本。

## 1 第一次运行

在 VS Code 中打开完整 `HUAWEI` 项目文件夹，再选择“终端 → 新建终端”。下列命令均从**仓库根目录**运行，根目录中应能看到 `inspection_image`、`transmission_starter` 和 `ui` 三个文件夹：

```powershell
py -X utf8 transmission_starter/check_transmission.py
```

预期输出 13 项 `[通过]` 和 `13/13 项检查通过`。如果电脑只能使用 `python` 命令，把 `py` 换成 `python`。不要在显示 `>>>` 的 Python 交互窗口中输入这些命令。

检查脚本在临时目录创建二进制占位文件并在结束时删除；这些文件不是 JPEG，测试数字不是实验结果。它们用来检验排序、单位换算、错误输入和兼容性。

然后核对团队已有的第一张真实图片包：

```powershell
py -X utf8 transmission_starter/check_transmission.py --manifest "inspection_image/delivery_v2/meter01/payload/manifest.json" --rate 1
py -X utf8 transmission_starter/check_transmission.py --manifest "inspection_image/delivery_A_v1/meter01/manifest_A.json" --rate 1
```

第二条命令会自动识别 A 组；它不把整图清单误当成 16 块清单。第一条命令检查 B/C 使用同一组文件、总字节数相等、整图完成时间相等。

## 2 三组分别做什么

| 组别 | 输入 | 发送顺序 | ROI 完整到达时间 |
|---|---|---|---|
| A | `manifest_A.json` 和一个整图 JPEG | 只有整图文件；收齐后显示 | 等于整图文件完整到达时间 |
| B | `manifest.json`、缩略图和 16 块 JPEG | 缩略图 → `tile_00` 至 `tile_15` | 最后一个重点块完整到达时刻 |
| C | 与 B 完全相同的清单及文件 | 缩略图 → 重点块按编号 → 背景块按编号 | 最后一个重点块完整到达时刻 |

B/C 只改变发送顺序，不改变总字节、最终画质或整图完成时间。A 与 B/C 的编码方式和文件数量不同，总字节数可能不同，必须分别统计。A 的 ROI 到齐时间表示对应像素已经可用，不能当作读数正确率。

## 3 已接通的输入字段

所有路径都相对于各自 manifest 所在目录，用 `/` 分隔，不接受绝对路径或越出该目录的路径。字节数必须是保存后的文件大小，不能填像素数或估计值。不同条目不能指向同一个文件。

### 团队分块图片包

`thumbnail` 对象包含 `payload` 和 `size_bytes`；`tiles` 列表必须有 16 项，使用：

| 字段 | 含义 |
|---|---|
| `tile_id` | 整数 0 至 15，不能重复或遗漏 |
| `payload` | 图块文件的相对路径 |
| `size_bytes` | 图块实际字节数，正整数 |
| `priority` | **1 为重点，0 为背景** |
| `total_size_bytes` | 如果存在，必须等于缩略图加所有图块的实际字节总量 |

清单中的 ROI、坐标、质量等其他字段由图片和接收模块使用；传输模块不重新判断哪些块与 ROI 相交。不能按 `priority` 从小到大直接排序，否则会先发背景。

### A 组整图包

清单使用 `group: "A"`、`image_id`、`payload`、`size_bytes`、`width`、`height`；尺寸必须为正整数，图片编号不能为空。若带 `total_size_bytes`，必须等于整图实际字节数。A 组不带缩略图或图块列表。

### 保留的旧接口

早期发送模块的 `thumbnail: {path, bytes}` 和 `tiles: [{id, path, bytes, is_roi}]` 仍可使用，图块 `id` 为 `tile_00` 至 `tile_15`，`is_roi` 为 JSON 布尔值。

早期界面 `packets` 清单也保留兼容：`packet_id`、`file`、`nbytes`、`priority`。这里的 priority 是 **0 缩略图、1 重点、2 背景**，与团队图片包含义不同，程序会明确转换。

`manifest_interface_example.json` 是早期字段示意，含占位字节且没有对应文件；不能用于真实实验。直接使用上面的团队交付路径即可。

## 4 返回给界面的字段

调用 `simulate(manifest_path, rate_mbps, mode)`，返回 Python 字典：

| 字段 | 含义与单位 |
|---|---|
| `mode` | A、B 或 C |
| `rate_mbps` | 调用时给定的固定有效速率，Mbps |
| `timeline` | 按发送顺序排列的到达记录；A 为 1 条，B/C 为 17 条 |
| `total_bytes` | 所有发送文件实际字节数之和，bytes |
| `roi_complete_s` | 完整 ROI 到达时刻，秒；B/C 没有重点块时为 `None` |
| `image_complete_s` | 整图内容全部到达时刻，秒；B/C 包含先传缩略图的耗时 |

每条 `timeline` 记录包含：`sequence`（从 0 开始）、`id`、`path`、`is_roi`、`bytes`、`cumulative_bytes`、`start_s`、`arrival_s`。缩略图 ID 为 `thumbnail`，分块为 `tile_00` 至 `tile_15`，A 整图为 `full`。

图块传到一半不算收到；只有 `arrival_s <= 当前仿真时刻` 才可解码并显示该文件。缩略图只供预览，不能替代高清重点块。

## 5 导出时间表

仍在仓库根目录执行。以下命令把 CSV 放在界面日志目录，避免混进图片包：

```powershell
New-Item -ItemType Directory -Force "ui/logs"
py -X utf8 transmission_starter/transmission.py "inspection_image/delivery_A_v1/meter01/manifest_A.json" --rate 0.25 --mode A --csv "ui/logs/meter01_A_025.csv"
py -X utf8 transmission_starter/transmission.py "inspection_image/delivery_v2/meter01/payload/manifest.json" --rate 0.25 --mode B --csv "ui/logs/meter01_B_025.csv"
py -X utf8 transmission_starter/transmission.py "inspection_image/delivery_v2/meter01/payload/manifest.json" --rate 0.25 --mode C --csv "ui/logs/meter01_C_025.csv"
```

CSV 使用 UTF-8 BOM 编码，便于 Excel 打开；每行同时记录模式、速率和汇总指标。`None` 在 CSV 中为空字段，不是 0。重复输出到同一个名字会覆盖旧文件，换图或换速率时应相应修改文件名。

界面通过 Python 导入 `simulate` 后调用，不必运行命令行，也不需要等待与仿真时间等长的真实秒数。模块不会上传数据到网络。

## 6 每段代码负责什么

`transmission.py`：

- `_read_manifest` 识别 A、团队 B/C 或旧清单，转换内部字段，再逐个检查编号、类型、相对路径、文件大小和总量。它不解码 JPEG，也不写文件。
- `simulate` 检查速率和模式与清单是否匹配；按规定排序，累加整数 bytes，再计算每个完整文件到达时刻。A 只处理一个文件。
- `export_csv` 将已计算的时间表写出，不另算一套时间。
- `main` 读取终端参数，成功时输出 JSON，失败时给出原因并返回非零退出码。

`check_transmission.py`：

- `fixture` 故意创建倒序清单和大小不同的文件，以发现错误排序或错误的固定每块时长。
- `check_pair` 验证 B/C 顺序、同一批文件、每行累计字节与时间、ROI 到齐和整图到齐。
- `check_full` 验证 A 单文件、字节换算、ROI 与整图同一时刻完成。
- `run_tests` 检查 13 类情况，包括重点原本靠前时的零收益、全部/没有重点、三种清单兼容、A/B/C 模式错配、非法数据、CSV 和读取不修改文件。
- `main` 先运行这些逻辑检查，再按可选的 `--manifest` 核对一个真实图片包。

## 7 时间公式和实验边界

1 Mbps = 1,000,000 bit/s；1 byte = 8 bit。

每个文件的开始时刻 = 此前文件累计字节 × 8 ÷ (有效速率 × 1,000,000)。

每个文件的完整到达时刻 = 包括该文件的累计字节 × 8 ÷ (有效速率 × 1,000,000)。

例如仅作手算练习：1 Mbps 下，一个 125,000 bytes 文件需要 1 秒。程序从累计整数 bytes 直接计算时刻，不逐次累加已舍入的小数。

正式实验先固定图片、ROI、编码参数和文件版本；每图在 0.25、1、5 Mbps 下运行 A/B/C，保留零改善或效果差的图片。B/C ROI 提前量为 B 时间减 C 时间，不能为了得到更好的结果重新编号或挑选样本。

当前计算的是固定有效速率下 JPEG 载荷的调度时间，不包含 TCP/IP 头、握手、连接时延、丢包、重传和处理时延。这些速率是仿真参数，不是实测 5G 性能。图像编码、解码耗时需另行记录，不能混成无线传输实测结果；人工读数、自动识别和动态画质不属于本模块。
