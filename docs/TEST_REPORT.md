# ImageFlow 1.1.0 验证报告

验证日期：2026-10-22（Asia/Shanghai）。实际在当前 Windows 机器上执行。

## 环境

| 项目 | 实际版本 |
|---|---|
| 系统 | Windows 11 x64，10.0.26200 |
| Python | 3.12.14 |
| PySide6 / Qt | 6.12.0 |
| Pillow | 13.0.0 |
| PyInstaller | 6.22.3 |
| pytest | 9.1.1 |
| FFmpeg / FFprobe | 9.0.2 essentials，gyan.dev 构建 |

开发环境使用独立 `.venv`。现有本地 FFmpeg/FFprobe 仅用于测试；不包含在便携包中。

## 自动化结果

**70 passed，0 failed，0 skipped；最终执行耗时 30.18 秒。**

命令：

```powershell
$env:IMAGEFLOW_FFMPEG='D:\贴纸\tools\ffmpeg\bin\ffmpeg.exe'
$env:IMAGEFLOW_FFPROBE='D:\贴纸\tools\ffmpeg\bin\ffprobe.exe'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -v -ra --junitxml=artifacts/test-results.xml
```

原始证据：`artifacts/test-output.txt`、`artifacts/test-results.xml`。

| 验收项 | 覆盖与结果 |
|---|---|
| FFmpeg 路径与能力检测 | 空路径、不存在路径、版本、编码器/解码器/容器解析通过 |
| 静态图片输入 | PNG/JPEG/WebP/BMP/TIFF/GIF 六种格式读取并转 PNG 通过 |
| 静态图片输出 | PNG/JPEG/WebP/BMP/TIFF 五种格式通过 |
| 静态 WebP → PNG | 输出尺寸、透明像素、半透明 alpha=128 和颜色检查通过 |
| JPEG 背景填充 | 指定 #3366cc 背景的输出像素误差检查通过 |
| GIF/APNG/动态 WebP | 3×3 九种互转组合，检查帧数、总时长、透明度、动画对象位置，通过 |
| 动画帧率 | 调整至 20fps 后时长及末帧顺序通过 |
| 动画循环 | GIF/WebP/APNG 的无限、一次、三次播放语义通过 |
| APNG 特殊情况 | 独立默认海报帧正确排除，通过 |
| VP9 Alpha WebM | 生成透明 VP9 样本，转 GIF/APNG/WebP 检查透明区域，通过 |
| 缺少 VP9 Alpha 解码器 | 明确阻止不能可靠保留透明背景的转换，通过 |
| 图片编辑 | 原图裁剪、百分比缩放、90°/任意角度旋转、翻转组合通过 |
| 批量 Telegram 分流 | 静态自动 PNG、动态自动 GIF；输入 SHA-256 不变，通过 |
| 路径与名称 | 中文、空格、emoji、&、%03d 等名称通过 |
| 输出冲突 | 自动改名、跳过、覆盖已有输出、目录结构、发布竞态保护通过 |
| 输入文件保护 | 同路径、跨任务输入保护、原文件内容不变，通过 |
| 失败隔离与重试 | 无效参数或子进程失败不阻断后续任务；修正运行环境后重试通过 |
| 中途取消 | Python 子进程、Windows 子进程树、真实 FFmpeg 运行取消、等待任务取消通过 |
| 临时文件清理 | 转换失败、达不到 GIF 体积限制时不发布文件且清理临时目录，通过 |
| 配置 | 重启读取、损坏 JSON 容错、不可写目录回退、非法数值约束通过 |
| GUI | 六页面导航、主题、真实导入→队列→转换、鼠标裁剪通过 |
| 自定义分流 | 按内容/静态动画/顺序/启停匹配，默认回退，真实混合批次输出 BMP/WebP/GIF，通过 |
| 自动保存 | 默认格式、规则、处理参数、裁剪、目录、并发、主题重启恢复，关闭立即保存、参数快照隔离通过 |
| 跟随系统主题 | 模拟 Qt 系统深浅变化信号及手动主题优先级，通过；未修改本机 Windows 外观设置 |
| 一键配置 | 本地工具复用、GUI 路径保存、下载校验、范围续传、取消、异常 ZIP 拒绝、临时清理通过 |
| 预览 | RGBA 首帧回调、WebM 透明度/时序、卡住时取消、缓存容量与文件失效、选择状态保持，通过 |

## 下载与预览速度

- 实际从 gyan.dev 下载完整 FFmpeg ZIP，SHA-256 校验后解压并检测 FFmpeg/FFprobe 9.0.2 成功，耗时 148.234 秒。证据：`artifacts/tool-download-check.json`。首轮网络提前断开时正确拒绝不完整下载；随后补充续传和范围校验测试。下载速度取决于网络。
- 同机同一份确定性生成的 512×512、3 秒、60 帧透明 VP9 WebM：旧实现完整加载 2.47–2.57 秒后显示；新实现首帧 0.035–0.038 秒，全部预览帧 0.091–0.097 秒。新版预览最高 400 像素 / 20fps，不改变转换质量。
- 这是合成样本解码基准，不包含文件导入探测或 GUI 绘制，也不保证任意机器/素材具有相同速度。证据：`artifacts/preview-benchmark/before.json`、`after.json`；脚本 `scripts/benchmark_preview.py --after`。

## 便携版验证

- 已使用 PyInstaller 在 Windows 上生成 `dist-v1.1/ImageFlow/ImageFlow.exe`，目录布局，无需安装器。旧版 `dist` 保留。
- 已检查 Qt DLL 实际加载，不含 FFmpeg/FFprobe 可执行文件。
- 已在独立工作目录启动 EXE，PATH 仅为 `C:\WINDOWS\System32`，去除了 Python 虚拟环境和 Qt 插件环境配置。
- **离屏 Qt**：页面切换、透明 WebP → PNG、中文路径与透明像素检查、分流规则保存、WebM 首帧/动画预览成功，退出码 0，整次验证 1.235 秒。
- **原生 Windows Qt**：实际显示窗口，同样完成上述检查，退出码 0，整次验证 1.687 秒。这里的耗时包括 GUI 与转换，不是单独的启动速度基准。
- 原始报告：`artifacts/package-verification.json`；窗口截图：`artifacts/packaged-windows/packaged-window.png`。

1.0 首轮打包曾发现 `QtWidgets` DLL 加载失败：打包环境 PATH 中另一工具的 `icuuc.dll` 使用带版本后缀的符号，与 Qt 要求的 Windows ICU API 不兼容。1.1 保留隔离构建 PATH、拒绝第三方目录污染、排除系统 ICU/UCRT 的修复，并重新执行上述两个 EXE 测试。

## 界面检查

实际 Qt 控件截图已查看，包括浅色、深色、1000×720 最小窗口、队列和设置页。证据位于 `artifacts/ui-*.png`。预览使用自生成透明动画样本，未改动用户贴纸文件。

## 尚未验证 / 明确限制

- 没有在另一台完全干净的 Windows 10/11 机器或虚拟机上运行；当前结论是本机 Windows EXE 在最小 PATH 下已成功运行。Windows 10 建议 1809 或更新版本，尚未实机验证。
- 未验证所有发行版 FFmpeg、所有异常图片或所有屏幕缩放比例。能力检测和任务日志用于对这些差异给出明确反馈。
- 未执行用户真实 Telegram 素材全集和 QQ 客户端上传验收；测试使用确定性自生成样本。QQ 各客户端行为仍需实际验证。
- TGS 暂不支持渲染；多页 TIFF 明确拒绝；8 位处理、EXIF 方向、ICC/元数据、超大动画、预览上限等限制详见 README。
- 未做代码签名、自动更新或崩溃任务恢复；未宣称 GIF 能无损保存原始色彩和半透明。
