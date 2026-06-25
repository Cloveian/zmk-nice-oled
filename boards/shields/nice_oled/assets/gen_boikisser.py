#!/usr/bin/env python3
"""Convert PNG frames to LVGL LV_IMG_CF_INDEXED_1BIT C arrays for use as an
lv_animimg animation in ZMK / zmk-nice-oled.

Text is optionally baked into selected frames at compile-time by extending
the image height with a text area — no changes to animation.c or timing code
required.

Usage:
    python3 gen_boikisser.py frames/ -o boikisser.c
    python3 gen_boikisser.py frames/ --text "mrow" --text-frames 3,4,5,6 --text-height 12
"""

import argparse
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# ── helpers ────────────────────────────────────────────────────────────────────


def iter_png_frames(directory):
    """Yield (basename_stem, full_path) sorted for every .png in *directory*."""
    if not os.path.isdir(directory):
        sys.exit(f"error: '{directory}' is not a directory")
    pngs = sorted(
        f for f in os.listdir(directory) if f.lower().endswith(".png")
    )
    if not pngs:
        sys.exit(f"error: no PNG files found in '{directory}'")
    for png in pngs:
        yield os.path.splitext(png)[0], os.path.join(directory, png)


def encode_1bit(image):
    """Return (pixel_data: list[int], w: int, h: int) for 1-bit packed encoding."""
    w, h = image.size
    row_bytes = math.ceil(w / 8)
    data = []
    for y in range(h):
        byte_val, bit_pos = 0, 7
        for x in range(w):
            r, g, b, a = image.getpixel((x, y))
            if a > 128 and (r + g + b) / 3 < 128:
                byte_val |= (1 << bit_pos)
            bit_pos -= 1
            if bit_pos < 0:
                data.append(byte_val)
                byte_val, bit_pos = 0, 7
        if bit_pos != 7:
            data.append(byte_val)
    return data, w, h


def c_array_literal(name, pixel_data, invert):
    """Return a C string with a static const uint8_t array for LVGL."""
    palette = (
        "  0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff,"
        if invert else
        "  0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0xff,"
    )
    hex_vals = [f"0x{b:02x}" for b in pixel_data]
    lines = [
        f"static const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_IMG_{name.upper()}",
        f"    uint8_t {name}_map[] = {{",
        f"#if CONFIG_NICE_OLED_WIDGET_INVERTED",
        f"  /*Palette: Idx 0: Black (#if), Idx 1: White (#if)*/",
        f"  0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff,",
        f"#else",
        f"  /*Palette: Idx 0: White (#else), Idx 1: Black (#else)*/",
        palette,
        f"#endif",
        f"",
        f"  /* Pixel data (1 bit per pixel) */",
    ]
    for i in range(0, len(hex_vals), 16):
        chunk = hex_vals[i:i+16]
        suffix = "," if i + 16 < len(hex_vals) else ""
        lines.append("  " + ", ".join(chunk) + suffix)
    lines.append("};")
    return "\n".join(lines)


# ── main ───────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="Generate LVGL 1-bit animation C arrays from PNG frames"
    )
    ap.add_argument("frames_dir", help="directory containing source PNG frames")
    ap.add_argument(
        "-o", "--output", default="boikisser.c",
        help="output C file (default: boikisser.c)",
    )
    ap.add_argument(
        "--text", default="",
        help="text to overlay on the animation (empty = disabled)",
    )
    ap.add_argument(
        "--text-frames", default="3,4,5,6",
        help="comma-separated 1-indexed frame numbers to show the text on (default: 3,4,5,6)",
    )
    ap.add_argument(
        "--text-height", type=int, default=12,
        help="height in px added above each frame for the text area (default: 12)",
    )
    ap.add_argument(
        "--symbol-prefix", default="boikisser",
        help="C symbol prefix for lv_img_dsc_t and data arrays (default: boikisser)",
    )
    args = ap.parse_args()

    # Parse text frame set
    text_frames = set()
    if args.text:
        for part in args.text_frames.split(","):
            try:
                text_frames.add(int(part.strip()) - 1)  # 1-indexed → 0-indexed
            except ValueError:
                pass

    # Font
    try:
        font = ImageFont.load_default(size=8)
    except TypeError:
        font = ImageFont.load_default()

    frames = list(iter_png_frames(args.frames_dir))
    if not frames:
        sys.exit(f"error: no PNG files found in '{args.frames_dir}'")

    lines = []
    lines.append(f"/* Generated: {args.symbol_prefix} animation, {len(frames)} frames */")
    lines.append(f"/* Generator: gen_boikisser.py  --text \"{args.text}\" "
                 f"--text-frames {args.text_frames} --text-height {args.text_height} */")
    lines.append("#include <lvgl.h>")
    lines.append("")
    lines.append("#ifndef LV_ATTRIBUTE_MEM_ALIGN")
    lines.append("#define LV_ATTRIBUTE_MEM_ALIGN")
    lines.append("#endif")
    lines.append("")

    img_descriptors = []

    for idx, (stem, fpath) in enumerate(frames):
        sym = f"{args.symbol_prefix}_{idx}"

        # Load source and rotate 90° CW so it appears upright on the rotated display.
        cat_img = Image.open(fpath).convert("RGBA").rotate(-90, expand=True)
        cat_w, cat_h = cat_img.size  # w=portrait_y span, h=portrait_x span

        if args.text:
            # Extend frame in the portrait_y direction (PIL x-axis).
            w = args.text_height + cat_w
            h = cat_h
            frame = Image.new("RGBA", (w, h), (255, 255, 255, 0))
            frame.paste(cat_img, (args.text_height, 0))

            if idx in text_frames:
                # Draw text so it reads left-to-right across the portrait width.
                #
                # Draw into a scratch image with PIL_x = portrait_x, PIL_y = text_height,
                # then TRANSPOSE so text spans PIL_y = portrait_x in the final frame.
                text_tmp = Image.new("RGBA", (h, args.text_height), (255, 255, 255, 0))
                draw = ImageDraw.Draw(text_tmp)
                try:
                    bbox = draw.textbbox((0, 0), args.text, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except AttributeError:
                    tw, th = draw.textsize(args.text, font=font)
                tx = max(0, (h - tw) // 2)
                ty = max(0, (args.text_height - th) // 2)
                draw.text((tx, ty), args.text, fill=(0, 0, 0, 255), font=font)
                try:
                    text_rot = text_tmp.transpose(Image.Transpose.TRANSPOSE)
                except AttributeError:
                    text_rot = text_tmp.transpose(Image.TRANSPOSE)
                frame.paste(text_rot, (0, 0))
        else:
            w, h, frame = cat_w, cat_h, cat_img

        pixel_data, w, h = encode_1bit(frame)
        data_size = 8 + len(pixel_data)  # 8-byte palette + pixels

        lines.append(f"#ifndef LV_ATTRIBUTE_IMG_{sym.upper()}")
        lines.append(f"#define LV_ATTRIBUTE_IMG_{sym.upper()}")
        lines.append(f"#endif")
        lines.append("")
        lines.append(c_array_literal(sym, pixel_data, False))
        lines.append("")

        img_descriptors.append((sym, w, h, data_size))

    for sym, w, h, data_size in img_descriptors:
        lines.append(f"const lv_img_dsc_t {sym} = {{")
        lines.append(f"  .header.cf = LV_IMG_CF_INDEXED_1BIT,")
        lines.append(f"  .header.always_zero = 0,")
        lines.append(f"  .header.reserved = 0,")
        lines.append(f"  .header.w = {w},")
        lines.append(f"  .header.h = {h},")
        lines.append(f"  .data_size = {data_size},")
        lines.append(f"  .data = {sym}_map,")
        lines.append(f"}};")
        lines.append("")

    out_str = "\n".join(lines)
    with open(args.output, "w") as f:
        f.write(out_str)

    w0, h0 = img_descriptors[0][1], img_descriptors[0][2]
    print(f"Wrote {args.output}")
    print(f"Frames: {len(frames)}, size: {w0}×{h0}, data_size: {img_descriptors[0][3]}")
    if args.text:
        # The text area was added before the cat in PIL_x (= portrait_y).
        # The KEYBOARD config needs CONFIG…ANIMATION_PERIPHERAL_CUSTOM_X
        # reduced by text_height to keep the cat at the same screen position.
        print(f"\nText: \"{args.text}\" on frames {sorted(f+1 for f in text_frames)} "
              f"(height={args.text_height} px)")
        print(f"Set CONFIG_…ANIMATION_PERIPHERAL_CUSTOM_X to its current value "
              f"minus text_height ({args.text_height}) to compensate.")


if __name__ == "__main__":
    main()