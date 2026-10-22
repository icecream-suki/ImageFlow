"""Ordered, content-based format routing shared by the UI and conversion engine."""
INPUT_FORMATS = {"any", "png", "jpeg", "webp", "bmp", "tiff", "gif", "apng", "webm"}
OUTPUT_FORMATS = {"png", "jpeg", "webp", "bmp", "tiff", "gif", "apng"}
ALIASES = {"jpg": "jpeg", "tif": "tiff"}


def clean_rules(value):
    if not isinstance(value, list):
        return []
    rules = []
    for item in value[:100]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("source", "kind", "target")):
            continue
        if (item.get("source") in INPUT_FORMATS and item.get("kind") in {"any", "static", "animated"}
                and item.get("target") in OUTPUT_FORMATS and type(item.get("enabled", True)) is bool):
            rules.append({"enabled": item.get("enabled", True), "source": item["source"],
                          "kind": item["kind"], "target": item["target"]})
    return rules


def resolve_output(media, image_format, animation_format, rules):
    source = ALIASES.get(media.format.lower(), media.format.lower())
    kind = "animated" if media.animated else "static"
    for index, rule in enumerate(rules):
        if (rule.get("enabled", True) and rule["source"] in {"any", source}
                and rule["kind"] in {"any", kind}):
            return rule["target"], f"规则 {index + 1}"
    return (animation_format, "默认动画格式") if media.animated else (image_format, "默认图片格式")
