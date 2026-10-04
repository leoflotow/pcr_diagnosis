"""用 ReportLab 生成两份参赛阅读版 PDF，并打包允许公开的源码与说明。

文档生成使用 Codex bundled Python；不读取密钥、课堂库或学生图像。
"""

import hashlib
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "docs" / "competition"
sys.path.insert(0, str(ROOT))
from branding import PRODUCT_NAME


def footer(canvas, doc):
    canvas.setFont("Chinese", 8)
    canvas.setFillColor(colors.HexColor("#68716F"))
    canvas.drawString(42, 26, f"{PRODUCT_NAME} · AI+教学参赛准备版 · 真实课堂效果待验证")
    canvas.drawRightString(A4[0] - 42, 26, str(doc.page))


def make_pdf(source):
    styles = {
        1: ParagraphStyle("title", fontName="Chinese", fontSize=20, leading=29, spaceAfter=14, textColor=colors.HexColor("#1F4B43")),
        2: ParagraphStyle("section", fontName="Chinese", fontSize=13, leading=21, spaceBefore=15, spaceAfter=7, keepWithNext=True, textColor=colors.HexColor("#1F4B43")),
        3: ParagraphStyle("subsection", fontName="Chinese", fontSize=11, leading=18, spaceBefore=9, spaceAfter=5, keepWithNext=True),
        0: ParagraphStyle("body", fontName="Chinese", fontSize=10, leading=17, spaceAfter=8, wordWrap="CJK", alignment=TA_LEFT),
    }
    story = []
    for block in source.read_text(encoding="utf-8").strip().split("\n\n"):
        heading = re.match(r"^(#{1,3}) (.*)$", block)
        if heading:
            story.append(Paragraph(escape(heading.group(2)), styles[len(heading.group(1))]))
        else:
            for line in block.splitlines():
                line = re.sub(r"`([^`]+)`", r"\1", line)
                story.append(Paragraph(escape(line), styles[0]))
    SimpleDocTemplate(str(source.with_suffix(".pdf")), pagesize=A4, rightMargin=42, leftMargin=42,
                      topMargin=42, bottomMargin=45, title=f"{PRODUCT_NAME} · {source.stem}", author="参赛负责人待补充").build(story, onFirstPage=footer, onLaterPages=footer)


def make_support_zip():
    # 明确白名单；不遍历 .env、secrets、data、uploads、.venv、Git 或用户原稿。
    names = ["branding.py", "README.md", "AGENTS.md", "RULE_AUDIT.md", "DESIGN_SYSTEM.md", "requirements.txt", "app.py", "core.py", "case_storage.py",
             "diagnosis_normalization.py", "diagnosis_rule_engine_v2.py", "evidence_support.py", "followup_agent.py", "navigation_state.py",
             "ui_design.py", "ui_design.css", "streamlit_launcher.py", "demo_runner.py", "demo_cases.json", "course_presets.json",
             "rules.csv", "rule_combos.csv", "rules_v2.csv"]
    files = [ROOT / name for name in names]
    files += list((ROOT / "pages").glob("*.py")) + list((ROOT / "tests").glob("*.py"))
    files += [ROOT / "scripts" / "verify_competition_ui.py", ROOT / "scripts" / "build_competition_materials.py", ROOT / "scripts" / "generate_demo_diagrams.py"]
    files += [ROOT / "demo_assets" / f"case_{index}.png" for index in range(1, 4)]
    files += [path for path in MATERIALS.iterdir() if path.is_file() and path.suffix in {".md", ".pdf", ".csv"}]
    manifest = []
    output = MATERIALS / "支持材料_源码与说明.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            data = path.read_bytes()
            name = path.relative_to(ROOT).as_posix()
            archive.writestr(name, data)
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        archive.writestr("文件校验清单.txt", ("\n".join(manifest) + "\n").encode("utf-8"))
    assert output.stat().st_size < 100 * 1024 * 1024
    print(f"支持包：{len(manifest)} 个文件，{output.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    pdfmetrics.registerFont(TTFont("Chinese", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    for name in ["02_作品介绍.md", "03_演示录屏脚本.md"]:
        make_pdf(MATERIALS / name)
    make_support_zip()
