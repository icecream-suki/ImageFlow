# ImageFlow 当前状态

更新：2026-10-22。当前版本 **1.1.0**；六项体验调整已实现并完成本机测试与 Windows EXE 验证。

## 已完成

- 六页面中文 Qt 界面、深色/浅色/跟随系统、文件/文件夹拖放、递归扫描、静态及动画预览、鼠标裁剪。已移除全局输出格式与导入格式筛选。
- FFmpeg/FFprobe 手动路径、同目录/PATH 查找、版本和能力检测；一键配置先检测本地工具，缺失时 HTTPS 下载、续传、SHA-256 校验后安装到配置目录，支持取消。
- 「图片格式转换」页集中默认图片/动画格式与自定义分流，支持输入格式和静态/动画条件、首条匹配、启停及排序；移除 Telegram 专用开关。选项约 400ms 自动保存，正常关闭刷新保存。
- 静态格式转换、等比/指定尺寸/百分比缩放、裁剪、旋转、翻转、JPEG/WebP 质量、WebP 无损与透明背景填充。
- GIF/APNG/动态 WebP 互转、帧率/循环/调色板参数、GIF 体积限制，支持透明 VP8/VP9 WebM 贴纸。旧显式格式及 Telegram 参数 API 保留兼容，GUI 统一使用新规则。
- 批量队列、进度、取消、失败重试、技术日志、大小对比、目录结构及冲突策略；临时输出和原图保护。
- Windows 运行/测试/打包脚本、便携 EXE、源码与便携 ZIP、README 和第三方许可证。

## 核心文件

| 文件 | 职责 |
|---|---|
| `run.py`、`imageflow/app.py` | 程序入口、Qt 启动、异常日志 |
| `imageflow/gui/` | `main.py` 页面与交互；`options.py` 参数；`settings.py` 设置；`preview.py` 播放/裁剪；`worker.py` 后台工作器 |
| `imageflow/models.py`、`config.py` | 媒体/参数/任务模型与校验；便携配置及回退 |
| `imageflow/capabilities.py`、`probe.py` | 工具路径/能力检测；媒体内容识别与扫描 |
| `imageflow/tool_setup.py`、`routing.py` | 一键工具配置/下载校验；按实际格式和动画类型顺序匹配输出 |
| `imageflow/commands.py`、`animation.py` | 参数与几何计算；动画合成帧及 WebP 时长校正 |
| `imageflow/process.py`、`engine.py`、`queue.py` | 子进程/取消；转换/安全发布/体积优化；线程池队列 |
| `tests/` | 核心规则、真实转换和 Qt GUI 测试 |
| `ImageFlow.spec`、`scripts/`、`imageflow/smoke.py` | 构建过滤、DLL 检查、EXE 冒烟验证、截图及分发 |

## 重要决定

- Pillow 按 disposal/blend 合成动画 RGBA 帧，排除 APNG 默认海报，使用毫秒时基 concat 交给 FFmpeg 变换/编码；不依赖 FFmpeg 的动态 WebP 解码支持。
- GIF 分两遍生成/使用调色板，避免整段缓存；体积限制最多尝试 7 次，未达标不发布。WebP 编码后只修正 ANMF 末帧延时，不重编码像素。
- 保留 WebM Alpha 时选择 `libvpx-vp9`/`libvpx`，缺失则报错；WebM 限无音频、VP8/VP9、宽高不超过 512、时长不超过 3.1 秒。
- 输出使用同卷临时目录、路径预留和安全发布；默认并发 2，范围 1–4。修改界面参数不改变已入队任务。
- 队列深拷贝规则与参数；运行中改并发延迟到批次结束，不丢弃等待任务。系统主题使用 Qt `colorSchemeChanged`，手动主题优先。
- WebM 预览直接流式读 RGBA，无 APNG/PNG 中间编码；先显示首帧、独立后台池，缓存最多 8 项/128MB，文件修改后失效。预览降采样不影响输出参数。
- QtWidgets DLL 问题已修复并保留构建 PATH 隔离、ICU/UCRT 过滤与加载预检。新版位于 `dist-v1.1/ImageFlow`；旧 `dist` 保留，`build/failed-package` 不应分发。

## 已有验证与交付

- 2026-10-22：Windows 11 x64、Python 3.12.14、Qt 6.12.0、Pillow 13.0.0、FFmpeg 9.0.2 下 **70 通过，0 失败，0 跳过**。证据：`artifacts/test-results.xml`、`docs/TEST_REPORT.md`。
- 新 EXE 在仅含 System32 的 PATH 下通过离屏及原生 Windows GUI、透明 WebP→PNG、分流保存、WebM 透明预览验证，退出码均为 0；证据：`artifacts/package-verification.json`。
- 实际 FFmpeg 下载、校验和检测通过。合成 3 秒 WebM 预览从约 2.5 秒降为首帧约 0.04 秒、全帧约 0.10 秒；详细条件与证据见报告，不代表任意素材性能。
- 新发布目录 `dist-v1.1` 含便携 ZIP、源码 ZIP、SHA256SUMS；源码 ZIP 包含本文件和 AGENTS.md。旧便携配置可复制到新程序旁继续使用。
- 公开仓库：`https://github.com/icecream-suki/ImageFlow`。源码使用 `main`，Windows 便携版和校验文件通过 Releases 分发；本地配置、下载工具及旧构建不进入 Git。

## 已知限制与下一步

- TGS 暂不渲染，多页 TIFF 明确拒绝；当前主要为 8 位 RGBA，不支持完整 ICC/HDR/CMYK 工作流，不自动应用 EXIF 方向，元数据仅尽力保留。
- 图片动画预览上限 300 帧/约 64MB 像素；WebM 预览最高 400 像素/20fps。输入限制单帧 8000 万像素、10000 帧。动画临时序列需要磁盘空间；相同帧 WebP 可能合并为静态图。
- 下载依赖外部网络和构建源，可随时改用手动路径。系统主题已测试 Qt 信号响应，未主动更改用户 Windows 外观设置。
- 尚未在另一台干净 Windows 或 Windows 10 上实测，也未完成用户真实贴纸全集、QQ 导入、多种 FFmpeg 构建及 DPI 的验收。
- 优先补充上述跨机器/真实素材验收；随后考虑 EXIF/色彩管理、任务持久化与崩溃恢复、对比预览。TGS 独立渲染模块、代码签名和自动更新属于后续可选方向。
