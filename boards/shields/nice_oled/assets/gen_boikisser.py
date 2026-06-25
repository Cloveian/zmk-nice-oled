#!/usr/bin/env python3
"""Convert boikisser PNG frames → LVGL LV_IMG_CF_INDEXED_1BIT C array.

Text is optionally baked into selected frames at compile-time.
The image is made taller (text area above the cat) so animation.c
is untouched. Update CONFIG_NICE_OLED_WIDGET_ANIMATION_PERIPHERAL_CUSTOM_X
to 48 - TEXT_HEIGHT after regenerating.
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

FRAMES_DIR = "/home/cloveian/Downloads/boikisser-frames"
FRAME_FILES = [f"real{i}.png" for i in range(1, 9)]
OUT_NAME = "boikisser"

# ── Text overlay config ───────────────────────────────────────────────────────
BOIKISSER_TEXT = "mrow"     # text to show; set to "" to disable entirely
TEXT_FRAMES    = {2, 3, 4, 5}  # 0-indexed frames that show the text (3-6 = indices 2-5)
TEXT_HEIGHT    = 12             # pixels in portrait_y added above the cat
# After regenerating, set in zarne_oled.conf:
#   CONFIG_NICE_OLED_WIDGET_ANIMATION_PERIPHERAL_CUSTOM_X = 48 - TEXT_HEIGHT
# ─────────────────────────────────────────────────────────────────────────────

try:
    font = ImageFont.load_default(size=8)
except TypeError:
    font = ImageFont.load_default()

lines = []
lines.append(f"/* Generated: boikisser animation, {len(FRAME_FILES)} frames */")
lines.append("#include <lvgl.h>")
lines.append("")
lines.append("#ifndef LV_ATTRIBUTE_MEM_ALIGN")
lines.append("#define LV_ATTRIBUTE_MEM_ALIGN")
lines.append("#endif")
lines.append("")

img_descriptors = []

for idx, fname in enumerate(FRAME_FILES):
    sym = f"{OUT_NAME}_{idx}"
    SYM = sym.upper()
    path = os.path.join(FRAMES_DIR, fname)

    # Load source and rotate 90° CW so it appears upright on the rotated display.
    cat_img = Image.open(path).convert("RGBA").rotate(-90, expand=True)
    cat_w, cat_h = cat_img.size   # e.g. (31, 32) — w=portrait_y span, h=portrait_x span

    if BOIKISSER_TEXT:
        # Build a frame that is TEXT_HEIGHT px taller in the portrait_y direction.
        w = TEXT_HEIGHT + cat_w
        h = cat_h
        frame = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        # Cat sits at the end of the text area (PIL_x offset = TEXT_HEIGHT).
        frame.paste(cat_img, (TEXT_HEIGHT, 0))

        if idx in TEXT_FRAMES:
            # Draw text so it reads left-to-right across the 32 px portrait width.
            #
            # Coordinate mapping for the final frame (PIL):
            #   PIL x direction  →  portrait_y (LVGL X, long axis)
            #   PIL y direction  →  portrait_x (LVGL Y, short axis = 32 px wide)
            #
            # Draw text into a scratch image with PIL_x = portrait_x (32 px) and
            # PIL_y = TEXT_HEIGHT, then TRANSPOSE it (swap axes) so the text ends
            # up spanning PIL_y = portrait_x in the final frame.
            text_tmp = Image.new("RGBA", (h, TEXT_HEIGHT), (255, 255, 255, 0))
            draw = ImageDraw.Draw(text_tmp)

            # Measure text for centering.
            try:
                bbox = draw.textbbox((0, 0), BOIKISSER_TEXT, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:          # Pillow < 8
                tw, th = draw.textsize(BOIKISSER_TEXT, font=font)

            tx = max(0, (h - tw) // 2)          # centre across 32 px portrait width
            ty = max(0, (TEXT_HEIGHT - th) // 2) # centre within text_height band

            draw.text((tx, ty), BOIKISSER_TEXT, fill=(0, 0, 0, 255), font=font)

            # TRANSPOSE swaps (PIL_x, PIL_y): result is (TEXT_HEIGHT, h=32)
            # Text that ran in PIL_x now runs in PIL_y = portrait_x direction. ✓
            try:
                text_t = text_tmp.transpose(Image.Transpose.TRANSPOSE)
            except AttributeError:          # Pillow < 9
                text_t = text_tmp.transpose(Image.TRANSPOSE)

            frame.paste(text_t, (0, 0))
    else:
        w, h = cat_w, cat_h
        frame = cat_img

    # ── Encode frame as LV_IMG_CF_INDEXED_1BIT ────────────────────────────────
    row_bytes = math.ceil(w / 8)
    pixel_data = []
    for y in range(h):
        byte_val = 0
        bit_pos  = 7
        for x in range(w):
            r, g, b, a = frame.getpixel((x, y))
            if a > 128 and (r + g + b) / 3 < 128:
                byte_val |= (1 << bit_pos)
            bit_pos -= 1
            if bit_pos < 0:
                pixel_data.append(byte_val)
                byte_val = 0
                bit_pos  = 7
        if bit_pos != 7:
            pixel_data.append(byte_val)

    palette_bytes = 8   # 2 × RGBA
    data_size     = palette_bytes + len(pixel_data)

    lines.append(f"#ifndef LV_ATTRIBUTE_IMG_{SYM}")
    lines.append(f"#define LV_ATTRIBUTE_IMG_{SYM}")
    lines.append(f"#endif")
    lines.append("")
    lines.append(f"static const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_IMG_{SYM} uint8_t {sym}_map[] = {{")
    lines.append(f"#if CONFIG_NICE_OLED_WIDGET_INVERTED")
    lines.append(f"  /*Palette: Idx 0: Black (#if), Idx 1: White (#if)*/")
    lines.append(f"  0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff,")
    lines.append(f"#else")
    lines.append(f"  /*Palette: Idx 0: White (#else), Idx 1: Black (#else)*/")
    lines.append(f"  0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0xff,")
    lines.append(f"#endif")
    lines.append(f"")
    lines.append(f"  /*Pixel data (1 bit per pixel, 0=palette idx 0, 1=palette idx 1)*/")

    hex_vals = [f"0x{b:02x}" for b in pixel_data]
    for i in range(0, len(hex_vals), 16):
        chunk = hex_vals[i:i+16]
        lines.append("  " + ", ".join(chunk) + ("," if i + 16 < len(hex_vals) else ""))
    lines.append("};")
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

out      = "\n".join(lines)
out_path = f"/home/cloveian/projects/zmk-nice-oled/boards/shields/nice_oled/assets/{OUT_NAME}.c"
with open(out_path, "w") as f:
    f.write(out)

cat_w_orig = img_descriptors[0][1] - (TEXT_HEIGHT if BOIKISSER_TEXT else 0)
new_custom_x = 48 - TEXT_HEIGHT if BOIKISSER_TEXT else 48

print(f"Wrote {out_path}")
print(f"Frames: {len(FRAME_FILES)}, size: {img_descriptors[0][1]}×{img_descriptors[0][2]}, "
      f"data_size: {img_descriptors[0][3]}")
if BOIKISSER_TEXT:
    print(f"\nUpdate zarne_oled.conf:")
    print(f"  CONFIG_NICE_OLED_WIDGET_ANIMATION_PERIPHERAL_CUSTOM_X={new_custom_x}  "
          f"(was 48, moved up by TEXT_HEIGHT={TEXT_HEIGHT})")
