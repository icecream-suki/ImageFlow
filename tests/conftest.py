from pathlib import Path
import os
import shutil

import pytest
from PIL import Image, ImageDraw

from imageflow.capabilities import inspect


@pytest.fixture(scope="session")
def caps():
    ffmpeg = os.environ.get("IMAGEFLOW_FFMPEG") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("IMAGEFLOW_FFPROBE") or ""
    if not ffmpeg:
        pytest.skip("设置 IMAGEFLOW_FFMPEG / IMAGEFLOW_FFPROBE 以运行真实转换测试")
    return inspect(ffmpeg, ffprobe)


@pytest.fixture
def samples(tmp_path):
    folder = tmp_path / "中文 路径 🐱"
    folder.mkdir()
    frames = []
    for index in range(4):
        image = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8+index*6, 8, 24+index*6, 30), fill=(255, 30+index*50, 20, 255))
        draw.rectangle((4, 35, 12, 43), fill=(20, 200, 100, 128))
        frames.append(image)
    png = folder / "透明 & test %03d.png"
    frames[0].save(png)
    webp = folder / "静态.webp"
    frames[0].save(webp, lossless=True)
    gif = folder / "动画.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=[100, 200, 100, 300], loop=0, disposal=2)
    animated_webp = folder / "动态.webp"
    frames[0].save(animated_webp, save_all=True, append_images=frames[1:], duration=[100, 200, 100, 300], loop=0, lossless=True)
    apng = folder / "动态.apng"
    frames[0].save(apng, save_all=True, append_images=frames[1:], duration=[100, 200, 100, 300], loop=0, disposal=0, blend=0)
    return dict(folder=folder, frames=frames, png=png, webp=webp, gif=gif, animated_webp=animated_webp, apng=apng)
