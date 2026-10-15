# A/B/C 集成验收记录

日期：2026-10-15。范围：已有五张公开仪表图片包、原始 A 整图清单、B/C 分块清单、发送模块、接收端和 Streamlit 页面。此次检查不作为正式读数准确率或真实无线网络实验结果。

## 已执行的检查

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s ui -p "test_*.py" -v` | 30 项通过：新旧页面、桥接、包核验、接收因果性和实际包集成。 |
| `python transmission_starter/check_transmission.py` | 13 项通过：旧格式兼容、原始 A/B/C 格式、排序、计时和错误输入。 |
| 在 inspection_image 中运行 `python -m unittest -v test_image_processing.py test_image_processing_A.py` | 6 项通过：ROI/边界、非整除尺寸、EXIF、A/B/C 方向对应和输出隔离。 |
| 最新画面恢复耗时加入 JSON 后，重跑 `python -m unittest discover -s ui -p "test_shared_app.py" -v` | 2 项通过，核对日志中的时刻、字节数和恢复耗时。此项属于上述 30 项，不重复计数。 |
| 实际浏览器检查 | 共享包默认页可打开；meter01、0.25 Mbps 生成三组；开始时均为空白；C 重点到齐时 A 仍为空白，B/C 按已收图块恢复，页面提供三份 CSV 与参数 JSON。 |

共 49 项不同的软件测试通过。测试环境 Windows、Python 3.13、Pillow 12.3.0、Streamlit 1.65.0。AppTest 输出的 MainThread 缺少 ScriptRunContext 提示是其测试运行方式的提示，本轮没有页面异常或错误提示。

## 实际图片包核验

`test_shared_abc_integration.py` 对 meter01 至 meter05 分别运行 0.25、1、5 Mbps，共 15 种图片/速率配置、45 份 A/B/C 时间表。验证：

- 每个 JPEG 的实际大小及 SHA256 与清单一致；A 和 B/C 指向同一原图来源及尺寸。
- B/C 使用同一批文件，缩略图计入总量，总字节数和整图完成时间相同。
- C 先缩略图、再重点、最后背景；只有重点块全到齐才记为 ROI 到齐。
- A 使用自己的整图字节数，收齐前不解码，收齐后才显示完整图像。
- 实际 meter05 的 B/C 最终像素一致；A 不要求与独立分块 JPEG 像素一致。
- 保留“重点优先没有提前收益”的测试情况。
- 两份交付目录全部文件在仿真前后的哈希相同，没有新增适配清单或重新编码。

## 当前仍未完成

软件验收不替代人工读数实验。meter03/meter05 待人工确认，meter02/meter04 没有可确认答案；不能把候选文字计入正确率。尚未加入自动 ROI 检测、动态画质、丢包重传或真实 Wi-Fi/5G 收发。裁剪与编码目前只有图像处理总耗时，未分别测量。

日志的 `last_receiver_snapshot` 是最新画面恢复的一次测量，拖动时间轴后更新；不是累计解码或端到端时延。正式实验需另行制定观测时刻、样本和人工读数记录规则。
