"""Pure, testable FFmpeg argument construction. No shell and no user filter strings."""
from pathlib import Path
import math

from .models import Options, MediaInfo, FlowError
from .capabilities import MUXERS


def output_dimensions(media: MediaInfo, opts: Options):
    w, h = (opts.crop[2:4] if opts.crop else (media.width, media.height))
    if opts.resize == "fit":
        ratio = min(opts.width / w, opts.height / h)
        if opts.only_shrink:
            ratio = min(1, ratio)
        w, h = max(1, round(w * ratio)), max(1, round(h * ratio))
    elif opts.resize == "exact":
        w, h = (min(w, opts.width), min(h, opts.height)) if opts.only_shrink else (opts.width, opts.height)
    elif opts.resize == "percent":
        ratio = min(opts.percent, 100) / 100 if opts.only_shrink else opts.percent / 100
        w, h = max(1, round(w * ratio)), max(1, round(h * ratio))
    return w, h


def base_filters(media, opts):
    filters = ["format=rgba", "setsar=1"]
    if opts.crop:
        x, y, w, h = opts.crop
        filters.append(f"crop={w}:{h}:{x}:{y}:exact=1")
    if opts.resize != "original":
        w, h = output_dimensions(media, opts)
        filters.append(f"scale={w}:{h}:flags={opts.interpolation}")
    rotation = opts.rotation % 360
    if rotation == 90:
        filters.append("transpose=1")
    elif rotation == 180:
        filters += ["hflip", "vflip"]
    elif rotation == 270:
        filters.append("transpose=2")
    elif rotation:
        angle = math.radians(rotation)
        filters.append(f"rotate={angle:.10f}:ow=rotw({angle:.10f}):oh=roth({angle:.10f}):c=none")
    if opts.hflip:
        filters.append("hflip")
    if opts.vflip:
        filters.append("vflip")
    if media.animated and opts.fps:
        filters.append(f"fps=fps={opts.fps}:round=near")
    return filters


def input_command(caps, media, input_args=None):
    args = [caps.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y",
            "-filter_complex_threads", "1", "-threads", "2"]
    if input_args is None:
        input_args = []
        if media.format == "WEBM" and media.alpha is True:
            # Alpha is stored as WebM BlockAdditional, which native VP9 may ignore.
            decoder = "libvpx-vp9" if media.codec == "vp9" else "libvpx"
            if decoder in caps.decoders:
                input_args += ["-c:v", decoder]
        if media.format in {"GIF", "APNG"}:
            input_args += ["-ignore_loop", "1"]
        input_args += ["-noautorotate", "-i", str(media.path)]
    return args + input_args


def edit_graph(media, opts):
    fmt = opts.output_format(media)
    graph = "[0:v:0]" + ",".join(base_filters(media, opts)) + "[edited]"
    source = "edited"
    if not opts.preserve_alpha or fmt in {"jpeg", "bmp"}:
        # Make an opaque background of identical size/timestamps, then alpha composite.
        rgb = [int(opts.background[i:i+2], 16) for i in (1, 3, 5)]
        graph += ";[edited]split[fg][bg];[bg]lutrgb=" + ":".join(f"{c}={v}" for c, v in zip("rgb", rgb))
        graph += ",colorchannelmixer=aa=1[opaque];[opaque][fg]overlay=shortest=1:format=auto,format=rgba[flat]"
        source = "flat"
    return graph, source


def build_palette_command(caps, media, opts, palette: Path, input_args=None):
    opts.validate(media)
    caps.require("gif", media.animated, media.format == "WEBM" and media.alpha is True and opts.preserve_alpha, media.codec)
    caps.require("png")
    graph, source = edit_graph(media, opts)
    graph += f";[{source}]palettegen=max_colors={opts.colors}:reserve_transparent=1:stats_mode=full[out]"
    return input_command(caps, media, input_args) + [
        "-filter_complex", graph, "-map", "[out]", "-an", "-sn", "-dn", "-frames:v", "1", "-c:v", "png",
        "-threads", "1", "-progress", "pipe:1", "-nostats", "-f", "image2", "-update", "1", str(palette)]


def build_command(caps, media, opts, output: Path, input_args=None, final_delay=None, palette=None):
    opts.validate(media)
    fmt = opts.output_format(media)
    animated = media.animated and fmt in {"gif", "webp", "apng"}
    alpha_webm = media.format == "WEBM" and media.alpha is True and opts.preserve_alpha
    encoder = caps.require(fmt, animated, alpha_webm, media.codec)
    args = input_command(caps, media, input_args)
    graph, source = edit_graph(media, opts)
    if fmt == "gif":
        if palette is None:
            raise FlowError("GIF 转换需要先生成优化调色板。")
        args += ["-i", str(palette)]
        graph += (f";[{source}][1:v:0]paletteuse=dither={opts.dither}:"
                  f"alpha_threshold={opts.alpha_threshold}:diff_mode=rectangle[out]")
    else:
        graph += f";[{source}]null[out]"
    args += ["-filter_complex", graph, "-map", "[out]", "-an", "-sn", "-dn", "-c:v", encoder, "-threads", "2"]
    args += ["-map_metadata", "-1" if opts.strip_metadata else "0"]
    if animated:
        args += ["-fps_mode", "vfr"]
        if media.duration:
            args += ["-t", f"{media.duration:.6f}"]
    else:
        args += ["-frames:v", "1"]
    if fmt == "jpeg":
        args += ["-q:v", str(max(2, round(31 - opts.quality * 29 / 100))), "-pix_fmt", "yuvj444p"]
    elif fmt == "webp":
        args += ["-quality", str(opts.quality), "-lossless", str(int(opts.lossless_webp)),
                 "-compression_level", "6", "-pix_fmt", "bgra" if opts.lossless_webp else "yuva420p"]
        if animated:
            args += ["-loop", str(opts.loops)]
    elif fmt == "png":
        args += ["-compression_level", "9", "-pix_fmt", "rgba"]
    elif fmt == "gif":
        args += ["-loop", str(0 if opts.loops == 0 else -1 if opts.loops == 1 else opts.loops - 1)]
        if animated and final_delay:
            args += ["-final_delay", str(max(1, round(final_delay * 100)))]
    elif fmt == "apng":
        args += ["-plays", str(opts.loops), "-pix_fmt", "rgba"]
        if animated and final_delay:
            args += ["-final_delay", f"{max(1, round(final_delay * 1000))}/1000"]
    elif fmt == "tiff":
        args += ["-pix_fmt", "rgba", "-compression_algo", "deflate"]
    elif fmt == "bmp":
        args += ["-pix_fmt", "bgr24"]
    args += ["-progress", "pipe:1", "-nostats", "-f", MUXERS[fmt]]
    if MUXERS[fmt] == "image2":
        args += ["-update", "1"]
    args.append(str(output))
    return args
