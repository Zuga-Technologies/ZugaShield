"""Render the ZugaShield logo + a Featured-card mockup. Edit, re-run, eyeball."""
import cairosvg
from PIL import Image, ImageDraw, ImageFont
import io, os

HERE = os.path.dirname(__file__)

# Security-blue -> teal palette. Shield body with a circuit "check" inside.
ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="{W}" height="{W}">
  <defs>
    <radialGradient id="bg" cx="50%" cy="38%" r="65%">
      <stop offset="0%" stop-color="#16233f"/>
      <stop offset="100%" stop-color="#0a0f1c"/>
    </radialGradient>
    <linearGradient id="shield" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#3dd2ff"/>
      <stop offset="55%" stop-color="#1f8fe0"/>
      <stop offset="100%" stop-color="#1456b8"/>
    </linearGradient>
    <linearGradient id="hi" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.40"/>
      <stop offset="45%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="112" fill="url(#bg)"/>
  <!-- shield body -->
  <path d="M256 96 L392 150 V268 C392 350 330 396 256 424 C182 396 120 350 120 268 V150 Z"
        fill="url(#shield)" stroke="#9fe8ff" stroke-width="6" stroke-opacity="0.55"/>
  <path d="M256 96 L392 150 V268 C392 350 330 396 256 424 C182 396 120 350 120 268 V150 Z"
        fill="url(#hi)"/>
  <!-- circuit check -->
  <g stroke="#06121f" stroke-width="30" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.92">
    <path d="M196 262 L240 308 L330 198"/>
  </g>
  <g fill="#06121f" opacity="0.92">
    <circle cx="196" cy="262" r="20"/>
    <circle cx="330" cy="198" r="20"/>
  </g>
</svg>"""

SIZES = [512, 256, 128, 64, 32]
for w in SIZES:
    cairosvg.svg2png(bytestring=ICON.format(W=w).encode(),
                     write_to=os.path.join(HERE, f"logo-{w}.png"),
                     output_width=w, output_height=w)
# master svg
with open(os.path.join(HERE, "logo.svg"), "w", encoding="utf-8") as f:
    f.write(ICON.format(W=512))

# ---- Featured-card mockup (1200x628, the LinkedIn link-preview ratio) ----
W, H = 1200, 628
card = Image.new("RGB", (W, H), (10, 15, 28))
dr = ImageDraw.Draw(card)
for y in range(H):  # vertical gradient bg
    t = y / H
    dr.line([(0, y), (W, y)], fill=(int(10+18*t), int(15+25*t), int(28+45*t)))
icon = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=ICON.format(W=320).encode(),
        output_width=320, output_height=320))).convert("RGBA")
card.paste(icon, (90, 154), icon)


def font(sz, bold=True):
    for p in [r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
              r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


dr.text((470, 196), "ZugaShield", font=font(96), fill=(235, 246, 255))
dr.text((474, 312), "AI Security Library", font=font(48), fill=(120, 200, 255))
dr.text((474, 384), "7-layer prompt-injection + secret-leak defense",
        font=font(34, False), fill=(170, 185, 210))
dr.text((474, 430), "MCP-aware  -  <15ms  -  pip install zugashield",
        font=font(34, False), fill=(170, 185, 210))
card.save(os.path.join(HERE, "mockup-card.png"))
print("wrote:", ", ".join(f"logo-{w}.png" for w in SIZES), ", logo.svg, mockup-card.png")
