# A组整图传输图片

已生成的 `inspection_image_delivery_A_v1.zip` 是两位队友共同使用的A组文件包。解压后 `delivery_A_v1/meter01` 至 `meter05` 各有一个 `full.jpg` 和 `manifest_A.json`。直接读取已有JPEG字节发送，无需重新压缩。原图、来源及正确答案沿用已交接的B/C五图包，不新增人工读数结论。

## 运行目录与命令

脚本在仓库的 **inspection_image子目录**。从仓库根目录执行：

```powershell
Set-Location inspection_image
python -m pip install -r requirements.txt
python image_processing_A.py --bc-package delivery_v2 --output-dir delivery_A_v1
```

使用Python 3.10以上；可将python替换为py或Python可执行文件完整路径。仓库已附生成结果，**不要重跑上述生成命令来消费交付包**。程序拒绝覆盖已有输出；需要新一轮实验时改用 `--output-dir delivery_A_run02`，新轮次耗时和JPEG字节以那一轮清单为准。

只验收现有结果（不会重新编码）：

```powershell
python image_processing_A.py --bc-package delivery_v2 --output-dir delivery_A_v1 --verify-only
```

独立ZIP也附本说明、image_processing_A.py、image_processing.py、requirements.txt。在解压后的delivery_A_v1目录内，若B/C包delivery_v2放在同级目录，可执行：

```powershell
python image_processing_A.py --bc-package ../delivery_v2 --output-dir . --verify-only
```

## 共同接口

包入口为 `package_index_A.json`：images列出五张的编号、清单与整图路径，路径相对于入口清单所在目录。每张的 `manifest_A.json` 中：

| 字段 | 约定 |
|---|---|
| image_id | meter01～meter05，与B/C相同 |
| group | A |
| payload | full.jpg，相对于该manifest_A.json所在目录 |
| width、height、mode | EXIF朝向校正后的完整尺寸，RGB，与B/C一致；不缩放 |
| quality | 80，与现有图块编码参数一致 |
| size_bytes、total_size_bytes | 该full.jpg落盘后的实际文件字节数 |
| image_processing_seconds | 本轮实测秒数；逐图计时，不是固定值或模拟传输时间 |
| source_sha256、payload_sha256 | 校验使用同一原图和同一编码文件 |

计时从读取原图前开始，含EXIF校正、RGB转换、创建单图输出目录、整图JPEG编码、落盘及读取实际文件长度；不含SHA256、写JSON、批量预检、验收、打ZIP、人工确认或传输模拟。与B/C计时同样在写manifest前结束，具体边界见processing_time_scope。

每张只编码一次完整JPEG；不复用缩略图或拼接已有有损块，不保存EXIF旋转标签。A组总传输字节数是五个full.jpg大小之和，不含JSON、说明、脚本、ZIP或协议开销。A组没有16块、缩略图或priority字段。

`verification_A.json` 记录五张完整解码、尺寸、字节验收，以及生成前后的B/C全包SHA256快照一致性。A组输出独立，不修改任何B/C JPEG、manifest或原图。两组质量参数相同不表示压缩后大小必须相同；每次传输耗时应读取对应组的真实size_bytes。
