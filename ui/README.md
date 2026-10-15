# 石韵涵：A/B/C 界面与接收端

这是三人的联合软件原型。默认直接读取邱雪瑶已经交付的五张图片包，调用朱雨萱的传输模块，显示石韵涵的接收画面和日志。已有的上传照片、设备 ROI 预设功能保留在第二个入口。

## 1. 在自己的电脑上启动

下载整个仓库，用 VS Code 打开根目录（能看到 inspection_image、transmission_starter、ui）。建议 Python 3.11 或更高版本。在终端依次执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ui/requirements.txt
.\.venv\Scripts\python.exe start_ui.py
```

第一行创建项目的独立 Python 环境；第二行安装 Pillow 和 Streamlit；第三行启动网页。如果电脑只有 `py` 命令，第一行改为 `py -3 -m venv .venv`。不需要激活环境，也不需要修改系统执行策略。以后只运行第三行。

启动器会选择 8501 到 8510 之间空闲端口并打开浏览器。终端按 Ctrl+C 关闭服务；仅关闭网页不会停止服务。

## 2. 第一次演示：使用共同图片包

1. 使用方式保持“共享图片包 A/B/C”。
2. 选择 meter01，速率选择 0.25 Mbps。
3. 展开“发送端 ROI、来源与人工核对记录”，检查红框。这里的原图预览只用于准备，接收端不会拿它铺底。
4. 点击“生成 A / B / C 对照”。三幅接收画面都从空白开始。
5. 点击“缩略图到齐”，B/C 开始出现低分辨率整图，A 继续等待自己的整图文件。
6. 点击“C 重点到齐”，观察普通顺序与重点优先的差别。可以勾选“同时放大接收端 ROI”。
7. 点击“A 整图到齐”“全部到齐”，核对整图显示。三个画面始终共用同一时间。
8. 下载 A、B、C 时间表和参数记录。四个文件也会自动写到 ui/logs。
9. 更换图片或速率后重新点击“生成”。这里只重新计算顺序和时间，不会重新压缩 JPEG。

共享模式固定使用交付 ROI，不提供临时改框，以免标注与已有 JPEG 的优先级不一致。meter01 已人工确认 3.23 V；meter03、meter05 待人工确认，meter02、meter04 没有可确认答案。待确认文字不会写入日志顶层 ground_truth，即使旧标注文件写了 use_for_reading_accuracy=true。

## 3. 自己上传图片、保存 ROI

1. 切换“上传与 ROI 调试 B/C”，运行模块保持“队友正式模块（软件仿真）”。
2. 选择公开仪表样本、上传 JPG/PNG/WebP，或从 ui/images 读取。内置测试图用于检查功能，数字不是实际仪表答案。
3. 填设备编号，检查红框是否完整覆盖数字、小数点和所需单位；四个坐标为左、上、右、下，右/下边界不包含在 ROI 内。
4. 填参考读数，确定无误才勾选人工核对。换图或改答案会取消旧确认。
5. 对固定设备、固定拍摄角度可保存 ROI 预设；尺寸一致仍需人工检查角度。
6. 点击“生成 B / C 对照”，使用共用时间轴和下载按钮。

同图同 ROI 改速率复用已有 JPEG；改图、ROI 或模块后重新生成。这个入口目前只做 B/C；A/B/C 的完整演示请用共同图片包。ui 自带的 Mendeley 五张电表调试照片，与 delivery_v2 五张图片是不同样本，不能混用编号或确认状态。其来源见 [SAMPLE_SOURCE.txt](SAMPLE_SOURCE.txt)。

## 4. 文件和主要代码段

| 文件 | 作用 |
|---|---|
| ../start_ui.py、start_app.py | 启动入口，不做图像或计时计算。 |
| start_environment.py | 找空闲端口、检查服务、打开浏览器、退出时关闭服务。 |
| app.py | 创建页面；默认转到共同包页面。原有六段流程依次处理来源、照片、ROI、生成、接收与日志。 |
| shared_view.py | 读取验收后的图片信息→生成三组时间表→保存记录→共用时间轴显示→下载。 |
| shared_package.py | 读取两份 package_index，核验原图、清单、JPEG 的对应关系、尺寸、质量、大小和 SHA256；判断人工确认状态。只读文件，不解码 JPEG。 |
| team_bridge.py | 调用队友模块，把返回字段转为界面统一字段；不另写计时算法，不生成适配清单。 |
| ui_support.py | ROI 预览与保存、只恢复已完整到达的 JPEG、导出 CSV。 |
| sample_data.py | 读取旧上传调试样本清单、来源、尺寸和 ROI。 |
| demo_backend.py | 独立的合成图片与旧接口测试后端。只有手动选择测试模块时使用。 |
| test_shared_package.py | 验证来源、大小、哈希、配对和人工确认状态。 |
| test_shared_abc_integration.py | 五张共同图片 × 三档速率 × 三组的实际集成验收，以及零收益例。 |
| test_shared_app.py | 检查新页面操作、时刻按钮、换图/速率、人工确认状态和日志。 |
| test_receiver_abc.py、test_receiver_integration.py | 检查未到齐不能解码，A 收齐显示，B/C 最终图一致。 |
| test_team_bridge.py、test_app_integration.py | 共同接口转换和旧上传调试入口回归检查。 |
| requirements.txt | 本项目使用的直接依赖和版本。 |

修改图片处理看 inspection_image；修改发送顺序/时间看 transmission_starter；修改页面布局看 shared_view.py 或 app.py；修改接收拼接看 ui_support.py。不要在界面里复制一份传输算法。

## 5. 共同接口

| 原始清单 | 传输返回/界面使用 |
|---|---|
| B/C tile_id 0..15 | tile_00..tile_15 |
| payload、size_bytes | 传输 path、bytes；界面 file、nbytes |
| box | 界面 bbox，格式 [x0,y0,x1,y1) |
| priority=1重点、0背景 | 传输 is_roi；界面内部缩略图0、重点1、背景2 |
| A group=A、payload=full.jpg | 一个 full 包，整图到齐时 ROI 也到齐 |
| timeline、image_complete_s | 界面 events、full_complete_s，单位秒 |
| image_processing_seconds | 界面换算为毫秒，并保留原计时范围 |

传输模块现在直接接受原始 A/B/C 清单，旧格式仍兼容。共享包内不再生成 manifest_for_transmission.json。B 先缩略图再编号顺序；C 先缩略图再重点、背景，各类内部按编号。A 没有缩略图，只有一个 full.jpg。

接收函数先建空白画布，完整到达才读文件、校验大小并解码。A 收齐才显示；B/C 缩略图铺底后逐块覆盖。界面中的发送端预览与接收端画布分开。

## 6. 日志与时间含义

共享模式每次生成写出 ui/logs/abc_<编号>_A.csv、_B.csv、_C.csv 和 _record.json。CSV 包含图片编号、组别、速率、包编号、优先级、字节数、开始/到达时间和累计字节。JSON 保存原图/清单/载荷指纹、ROI、来源与确认记录、模块指纹、相对仓库根目录的清单位置和全部时间表。image_processing 保存交付包图像处理总耗时；last_receiver_snapshot 保存最新一次接收画面的模拟时刻、字节数及实际恢复耗时，拖动时间轴后会更新，不累计成端到端耗时。

上传调试的数据放在 ui/data/ui_inputs 与 ui/data/ui_runs；设备预设在 ui/data/roi_presets.json；日志以 ui_ 开头，清单路径相对 ui 目录。个人图片、运行数据和日志默认不提交 Git。

SHA256 是核对文件是否相同的指纹。当前计时公式为：累计 JPEG 字节 × 8 ÷（Mbps × 1,000,000）。只计 JPEG 载荷，不含清单、协议头、丢包重传、传播时延。

B/C 必须总字节数和整图到齐时间相同，才能观察发送顺序的影响；A 单独整图编码，压缩效率不同，按它自身字节数计算。重点提前的幅度由图片与 ROI 决定，零收益样本必须保留。

表中的到达时间是计算值。交付包编码耗时是生成包时的历史实测；页面恢复耗时是本次解码、缩放、拼接的实测，不是累计端到端时延。拖动滑块的速度不会改变模拟传输结果。

当前日志标记“接口联调，非正式实验”。真实照片不等于真实网络实验；ROI 到齐不等于正确读出数字。后续需要先确认答案，再请观察者在指定时刻独立读数。自动识别、动态画质、真实 Wi-Fi/5G 收发尚未实现。

## 7. 运行检查

从仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s ui -p "test_*.py" -v
.\.venv\Scripts\python.exe transmission_starter/check_transmission.py
```

通过后再手工打开网页完成第 2 节的演示。实际检查记录见 [INTEGRATION_VALIDATION.md](INTEGRATION_VALIDATION.md)。测试通过仅表示对应的软件行为符合约定，不是正式读数准确率或通信性能结果。
