"""生成明确标为模拟的泳道教学示意，不模拟真实照片或片段数值。"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo_assets"
OUTPUT.mkdir(exist_ok=True)
FONT = "C:/Windows/Fonts/msyh.ttc"
title_font = ImageFont.truetype(FONT, 28)
text_font = ImageFont.truetype(FONT, 22)
small_font = ImageFont.truetype(FONT, 18)

for index, title in enumerate(["阳性与样本均无带", "阴性出现短片段", "样本拖尾或弥散"], 1):
    image = Image.new("RGB", (960, 520), "#F8F8F4")
    draw = ImageDraw.Draw(image)
    draw.text((30, 20), "模拟泳道示意图｜非实际电泳结果", font=title_font, fill="#A3422A")
    draw.text((30, 65), title, font=text_font, fill="#1F4B43")
    lane_x = [230, 390, 550, 710]
    for x, label in zip(lane_x, ["M", "阳性", "阴性 NTC", "样本"]):
        draw.rounded_rectangle((x-44, 140, x+44, 370), radius=7, fill="#E3ECE8", outline="#A8BDB4", width=2)
        draw.text((x-46, 108), label, font=text_font, fill="#294B42")
    for y in [175, 200, 235, 285, 330]:
        draw.rectangle((200, y, 260, y+7), fill="#3B756A")
    draw.line((320, 238, 795, 238), fill="#95B7AA", width=2)
    draw.text((30, 226), "目标位置（示意）", font=small_font, fill="#386456")
    if index in (2, 3):
        draw.rectangle((360, 234, 420, 242), fill="#275B50")
    if index == 2:
        draw.rectangle((520, 320, 580, 326), fill="#275B50")
        draw.rectangle((680, 234, 740, 242), fill="#275B50")
    if index == 3:
        for offset, color in enumerate(["#275B50", "#467B6D", "#639686", "#85B19F", "#B0CBBB"]):
            draw.rectangle((682-offset*2, 228+offset*15, 738+offset*2, 244+offset*15), fill=color)
    explanations = ["配液与对照记录用于排查共同体系，不能只归因为样本模板。", "比较相对位置；阴性短带不足以直接证明目标模板污染。", "形态为示意；结合上样单与同胶其他泳道区分原因。"]
    draw.text((30, 404), explanations[index-1], font=small_font, fill="#294B42")
    draw.text((30, 452), "Marker 条带及位置仅作图示，无 bp 标尺；系统不自动判读本图。", font=small_font, fill="#A3422A")
    image.save(OUTPUT / f"case_{index}.png")

print("三份模拟泳道示意已生成，无实际片段大小或真实实验数据。")
