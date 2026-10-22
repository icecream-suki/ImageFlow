# ImageFlow 项目规则

## 范围与技术栈

- Windows 本地图片工具：静态图片、GIF/APNG/动态 WebP，以及受限的 Telegram WebM 贴纸输入；不扩展到通用视频、音频或云端处理。
- Python 3.12+、PySide6-Essentials（Qt Widgets）、Pillow；用户指定本地 FFmpeg/FFprobe，按实际构建检测能力，不要求修改系统 PATH，不捆绑 FFmpeg。
- pytest 测试，PyInstaller 独立目录便携打包。依赖版本以 `requirements*.txt` 为准，兼容范围见 `pyproject.toml`。
- 默认简体中文，保留深浅主题、Unicode 路径与免管理员权限运行。

## 实现约束

- 保持 GUI、模型/校验、媒体识别、命令构建、执行、队列、配置分层；具体文件职责见 `PROJECT_STATE.md`。
- 扫描、探测、预览解码和转换在后台执行；通过 Qt 信号更新界面。任务使用参数快照和受控并发；取消/关闭必须结束子进程并清理临时文件。
- FFmpeg 使用 subprocess 参数列表调用，不使用 shell 拼接命令或接受任意用户滤镜字符串。
- 始终保护输入文件，含跨任务输入和路径别名；默认重名改名。先写目标磁盘上的临时文件，成功后安全发布，失败不得留下伪装成成功的输出。
- 动画以实际内容和时间戳识别；修改帧率不能改变播放速度。保留 GIF 两遍调色板、WebM Alpha 解码器选择和 WebP 末帧时长修正的语义。
- 动画转静态须明确允许首帧导出；不支持透明度时提示并填色。区分无损编码和恢复原图，未知属性不伪装成可靠检测值。TGS 不得交给 FFmpeg 假装支持。
- 配置优先写 `portable_config`，不可写时回退 `%LOCALAPPDATA%\ImageFlow` 并告知位置；保留损坏配置，避免直接崩溃。
- 默认输出和自定义分流统一走 `routing.py`，按实际内容及动画类型匹配，首条命中生效；修改规则不影响已入队任务。所有处理选项自动保存，关闭前刷新待保存更改；并发变更不取消已有任务。
- 跟随系统主题使用 Qt 系统色彩方案变化信号，显式深浅主题不受系统切换影响。预览先显示首帧并使用有容量限制的缓存，预览降采样不得改变实际输出参数。
- 仅用户点击一键配置时允许联网下载工具；优先复用本地 FFmpeg，不改系统 PATH。下载使用 HTTPS、续传范围检查和 SHA-256 校验，检测成功后才采用，保留上游许可证；发布包排除下载工具和用户配置。

## 运行与测试

以下命令从项目根目录执行；FFmpeg 路径换成实际位置：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe run.py
.\scripts\test.ps1 -FFmpeg 'D:\Tools\ffmpeg\bin\ffmpeg.exe' -FFprobe 'D:\Tools\ffmpeg\bin\ffprobe.exe'
```

- 可直接用 `.\.venv\Scripts\python.exe -m pytest -q -ra`；真实转换通过 `IMAGEFLOW_FFMPEG` / `IMAGEFLOW_FFPROBE` 配置，FFmpeg 也可从 PATH 查找。缺少工具的跳过项必须如实报告。
- 按改动验证参数、像素/透明度、动画时长与顺序、失败/取消、文件保护及 GUI 流程；不要只验证退出码或生成的命令文本。使用临时生成样本，不改用户素材。
- 纯文档修改不必重跑转换测试；引用已有结果时标明验证日期，不宣称本次重新执行。

## 打包与交付

```powershell
.\scripts\build.ps1 -Destination .\dist-next
.\.venv\Scripts\python.exe scripts\verify_package.py .\dist-next\ImageFlow\ImageFlow.exe
```

- 使用新的输出目录；不得为重建删除用户便携配置。`verify_package.py` 设置上述 FFmpeg 环境变量后才包含真实转换验证，并会短暂打开原生窗口。
- 保留构建 PATH 隔离、`ImageFlow.spec` 的 DLL 来源检查/过滤，以及 Qt DLL 加载预检；避免收集其他工具的同名 ICU DLL。仅构建成功不代表 EXE 可运行。
- 分发完整目录及许可证；发布压缩包脚本为 `scripts/package_release.py`，默认读取 `dist/ImageFlow`，拒绝覆盖现有 ZIP。
- `build/`、`dist*/`、`.venv/` 是构建/环境产物，不作为源码修改入口。当前状态记入 `PROJECT_STATE.md`，详细验证证据保留在 `docs/TEST_REPORT.md` 与 `artifacts/`。
