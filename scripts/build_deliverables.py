#!/usr/bin/env python3
"""Сборка оформленного DOCX, PPTX и текста выступления из артефактов проекта."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptRGB
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches as PInches, Pt as PPt

REPORT_MD = ROOT / "reports" / "Итоговый_отчёт.md"
DOCX_PATH = ROOT / "reports" / "Итоговый_отчёт.docx"
PPTX_PATH = ROOT / "reports" / "Презентация_проекта.pptx"
SPEECH_PATH = ROOT / "reports" / "Текст_выступления.md"
FIG = ROOT / "reports" / "figures"

NAVY = "172554"
BLUE = "2563EB"
CYAN = "0891B2"
INK = "0F172A"
MUTED = "64748B"
LIGHT = "E2E8F0"
WHITE = "FFFFFF"
RED = "DC2626"
GREEN = "059669"
AMBER = "D97706"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = "PAGE"
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)


def add_inline_markdown(paragraph, text: str) -> None:
    """Мини-парсер **bold**, `code` и *italic*."""
    pattern = re.compile(r"(\*\*.+?\*\*|`.+?`|(?<!\*)\*[^*]+?\*(?!\*))")
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            paragraph.add_run(text[cursor:match.start()])
        token = match.group(0)
        if token.startswith("**"):
            run = paragraph.add_run(token[2:-2])
            run.bold = True
        elif token.startswith("`"):
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10.5)
            run.font.color.rgb = RGBColor.from_string(BLUE)
        else:
            run = paragraph.add_run(token[1:-1])
            run.italic = True
        cursor = match.end()
    if cursor < len(text):
        paragraph.add_run(text[cursor:])


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(3)
    section.right_margin = Cm(1.5)
    section.different_first_page_header_footer = True

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(14)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.first_line_indent = Cm(1.25)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.space_after = Pt(0)
    pf.widow_control = True

    heading_specs = {
        "Title": (22, NAVY, WD_ALIGN_PARAGRAPH.CENTER),
        "Heading 1": (16, NAVY, WD_ALIGN_PARAGRAPH.CENTER),
        "Heading 2": (15, BLUE, WD_ALIGN_PARAGRAPH.LEFT),
        "Heading 3": (14, CYAN, WD_ALIGN_PARAGRAPH.LEFT),
    }
    for name, (size, color, align) in heading_specs.items():
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        style.paragraph_format.alignment = align
        style.paragraph_format.first_line_indent = Cm(0)
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(8)
        style.paragraph_format.keep_with_next = True

    for style_name in ["List Bullet", "List Number"]:
        style = doc.styles[style_name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(14)
        style.paragraph_format.left_indent = Cm(1.25)
        style.paragraph_format.first_line_indent = Cm(-0.6)
        style.paragraph_format.line_spacing = 1.5

    if "Code Block" not in [style.name for style in doc.styles]:
        style = doc.styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = "Consolas"
        style.font.size = Pt(9)
        style.font.color.rgb = RGBColor.from_string(INK)
        style.paragraph_format.left_indent = Cm(0.5)
        style.paragraph_format.right_indent = Cm(0.5)
        style.paragraph_format.space_before = Pt(4)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.0
        p_pr = style.element.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "F1F5F9")
        p_pr.append(shd)

    header = section.header.paragraphs[0]
    header.text = "Академический навигатор · Управление данными"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.runs[0].font.name = "Times New Roman"
    header.runs[0].font.size = Pt(9)
    header.runs[0].font.color.rgb = RGBColor.from_string(MUTED)
    add_page_number(section.footer.paragraphs[0])


def add_title_page(doc: Document) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("МИНИСТЕРСТВО НАУКИ И ВЫСШЕГО ОБРАЗОВАНИЯ РФ")
    r.bold = True; r.font.name = "Times New Roman"; r.font.size = Pt(12)
    for text in ["[НАИМЕНОВАНИЕ ОБРАЗОВАТЕЛЬНОЙ ОРГАНИЗАЦИИ]", "[ИНСТИТУТ / ФАКУЛЬТЕТ / КАФЕДРА]"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run(text); run.bold = True; run.font.size = Pt(12)
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run("ОТЧЁТ"); run.bold = True; run.font.size = Pt(20); run.font.color.rgb = RGBColor.from_string(NAVY)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run("по комплексу лабораторных работ\nпо дисциплине «Управление данными»"); run.bold = True; run.font.size = Pt(14)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0); p.paragraph_format.space_before = Pt(14)
    run = p.add_run("«Интеллектуальный агент-аналитик академической успеваемости и риска неуспеваемости\n“Академический навигатор”»")
    run.bold = True; run.font.size = Pt(16); run.font.color.rgb = RGBColor.from_string(BLUE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0); p.paragraph_format.space_before = Pt(12)
    p.add_run("Направление 09.03.03 «Прикладная информатика»\n4 курс, 8 семестр").font.size = Pt(12)
    for _ in range(3): doc.add_paragraph()
    table = doc.add_table(rows=2, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Cm(7.5); table.columns[1].width = Cm(7.5)
    values = [
        ("Выполнил(а):", "студент(ка) группы ______\nФ. И. О. __________________________"),
        ("Проверил(а):", "Ф. И. О. __________________________\nДолжность _________________________"),
    ]
    for row, values_row in zip(table.rows, values):
        for cell, value in zip(row.cells, values_row):
            cell.text = value
            for par in cell.paragraphs:
                par.paragraph_format.first_line_indent = Cm(0)
                par.paragraph_format.space_after = Pt(4)
                for run in par.runs: run.font.name = "Times New Roman"; run.font.size = Pt(12)
    # Скрываем границы таблицы.
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = OxmlElement(f"w:{edge}"); tag.set(qn("w:val"), "nil"); borders.append(tag)
    tbl_pr.append(borders)
    for _ in range(2): doc.add_paragraph()
    p = doc.add_paragraph("[ГОРОД] — 2026")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0)
    p.runs[0].bold = True; p.runs[0].font.size = Pt(12)
    p.add_run().add_break(WD_BREAK.PAGE)


def resolve_image(md_path: str) -> Path | None:
    path = (REPORT_MD.parent / md_path).resolve()
    if path.suffix.lower() == ".svg":
        mapped = FIG / f"{path.stem}.png"
        return mapped if mapped.exists() else None
    return path if path.exists() else None


def parse_report_into_docx(doc: Document) -> None:
    lines = REPORT_MD.read_text(encoding="utf-8").splitlines()
    # Пропускаем Markdown-титульник до первой горизонтальной линии.
    start = next((index + 1 for index, line in enumerate(lines) if line.strip() == "---"), 0)
    lines = lines[start:]
    i = 0
    code_mode = False
    code_lines: list[str] = []
    paragraph_buffer: list[str] = []
    first_h1 = True

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        text = " ".join(item.strip() for item in paragraph_buffer).strip()
        if text:
            p = doc.add_paragraph()
            add_inline_markdown(p, text)
        paragraph_buffer = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            if not code_mode:
                code_mode = True; code_lines = []
            else:
                p = doc.add_paragraph(style="Code Block")
                p.paragraph_format.first_line_indent = Cm(0)
                p.add_run("\n".join(code_lines))
                code_mode = False
            i += 1; continue
        if code_mode:
            code_lines.append(line); i += 1; continue
        if not stripped:
            flush_paragraph(); i += 1; continue
        if stripped == "---":
            flush_paragraph(); i += 1; continue
        image_match = re.match(r"!\[(.+?)\]\((.+?)\)", stripped)
        if image_match:
            flush_paragraph()
            caption, raw_path = image_match.groups()
            path = resolve_image(raw_path)
            if path:
                p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0)
                run = p.add_run(); run.add_picture(str(path), width=Inches(6.35))
                cap = doc.add_paragraph(f"Рисунок — {caption}")
                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER; cap.paragraph_format.first_line_indent = Cm(0); cap.paragraph_format.space_after = Pt(8)
                cap.runs[0].italic = True; cap.runs[0].font.size = Pt(11)
            i += 1; continue
        if stripped.startswith("#"):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if level == 1:
                if not first_h1:
                    doc.add_page_break()
                first_h1 = False
                p = doc.add_paragraph(style="Heading 1")
            elif level == 2:
                p = doc.add_paragraph(style="Heading 2")
            else:
                p = doc.add_paragraph(style="Heading 3")
            p.paragraph_format.first_line_indent = Cm(0)
            add_inline_markdown(p, text)
            i += 1; continue
        # Markdown table.
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-+", lines[i + 1].strip().lstrip("|")):
            flush_paragraph()
            rows = []
            rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
            i += 2  # skip separator
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
                i += 1
            cols = max(len(row) for row in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = "Table Grid"; table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for r_idx, values in enumerate(rows):
                for c_idx in range(cols):
                    cell = table.cell(r_idx, c_idx); cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    p = cell.paragraphs[0]; p.paragraph_format.first_line_indent = Cm(0); p.paragraph_format.space_after = Pt(0)
                    add_inline_markdown(p, values[c_idx] if c_idx < len(values) else "")
                    for run in p.runs:
                        run.font.name = "Times New Roman"; run.font.size = Pt(9.5)
                        if r_idx == 0: run.bold = True; run.font.color.rgb = RGBColor.from_string(WHITE)
                    if r_idx == 0: set_cell_shading(cell, NAVY)
                    elif r_idx % 2 == 0: set_cell_shading(cell, "F1F5F9")
            set_repeat_table_header(table.rows[0])
            doc.add_paragraph().paragraph_format.space_after = Pt(0)
            continue
        bullet = re.match(r"^[-*]\s+(.+)", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.+)", stripped)
        checkbox = re.match(r"^- \[[ xX]\]\s+(.+)", stripped)
        if checkbox:
            flush_paragraph(); p = doc.add_paragraph(style="List Bullet"); p.paragraph_format.first_line_indent = Cm(-0.6); add_inline_markdown(p, "☐ " + checkbox.group(1)); i += 1; continue
        if bullet:
            flush_paragraph(); p = doc.add_paragraph(style="List Bullet"); p.paragraph_format.first_line_indent = Cm(-0.6); add_inline_markdown(p, bullet.group(1)); i += 1; continue
        if numbered:
            flush_paragraph(); p = doc.add_paragraph(style="List Number"); p.paragraph_format.first_line_indent = Cm(-0.6); add_inline_markdown(p, numbered.group(1)); i += 1; continue
        if stripped.startswith("\\[") or stripped.startswith("\\]"):
            flush_paragraph(); i += 1; continue
        if stripped.startswith(">"):
            flush_paragraph(); p = doc.add_paragraph(); p.paragraph_format.left_indent = Cm(1); p.paragraph_format.first_line_indent = Cm(0); p.paragraph_format.space_after = Pt(6)
            run = p.add_run(stripped.lstrip("> ")); run.italic = True; run.font.color.rgb = RGBColor.from_string(MUTED)
            i += 1; continue
        paragraph_buffer.append(stripped)
        i += 1
    flush_paragraph()


def build_docx() -> None:
    doc = Document()
    configure_document(doc)
    add_title_page(doc)
    parse_report_into_docx(doc)
    core = doc.core_properties
    core.title = "Академический навигатор — итоговый отчёт"
    core.subject = "Комплекс лабораторных работ по дисциплине «Управление данными»"
    core.author = "[Ф. И. О. студента]"
    core.keywords = "управление данными, ETL, ML, интеллектуальный агент, Streamlit"
    doc.save(DOCX_PATH)


# ---------- Presentation helpers ----------
P_NAVY = PptRGB(11, 18, 32)
P_BLUE = PptRGB(37, 99, 235)
P_CYAN = PptRGB(6, 182, 212)
P_WHITE = PptRGB(255, 255, 255)
P_INK = PptRGB(15, 23, 42)
P_MUTED = PptRGB(100, 116, 139)
P_LIGHT = PptRGB(241, 245, 249)
P_RED = PptRGB(239, 68, 68)
P_GREEN = PptRGB(16, 185, 129)
P_AMBER = PptRGB(245, 158, 11)


def rect(slide, x, y, w, h, fill, radius=True, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, PInches(x), PInches(y), PInches(w), PInches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line or fill
    return shape


def text(slide, value, x, y, w, h, size=20, color=P_INK, bold=False, font="Aptos", align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(PInches(x), PInches(y), PInches(w), PInches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True; tf.vertical_anchor = valign
    p = tf.paragraphs[0]; p.alignment = align; p.text = value
    for run in p.runs:
        run.font.name = font; run.font.size = PPt(size); run.font.bold = bold; run.font.color.rgb = color
    return box


def rich_lines(slide, lines, x, y, w, h, size=17, color=P_INK, bullet=True, gap=8):
    box = slide.shapes.add_textbox(PInches(x), PInches(y), PInches(w), PInches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True; tf.margin_left = PInches(0.05); tf.margin_right = PInches(0.04)
    for idx, item in enumerate(lines):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = item; p.level = 0; p.space_after = PPt(gap); p.line_spacing = 1.1
        if bullet:
            p.text = "•  " + p.text
        for run in p.runs:
            run.font.name = "Aptos"; run.font.size = PPt(size); run.font.color.rgb = color
    return box


def base_slide(prs, title_value, number, eyebrow="АКАДЕМИЧЕСКИЙ НАВИГАТОР"):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background.fill; bg.solid(); bg.fore_color.rgb = P_WHITE
    rect(slide, 0, 0, 13.333, 0.16, P_BLUE, radius=False)
    text(slide, eyebrow, 0.58, 0.35, 8.5, 0.28, size=9, color=P_CYAN, bold=True)
    text(slide, title_value, 0.58, 0.72, 11.8, 0.7, size=27, color=P_NAVY, bold=True)
    text(slide, f"{number:02d}", 12.08, 0.34, 0.65, 0.34, size=12, color=P_MUTED, bold=True, align=PP_ALIGN.RIGHT)
    return slide


def metric(slide, label, value, x, y, w, color=P_BLUE, hint=""):
    rect(slide, x, y, w, 1.12, P_LIGHT, line=PptRGB(226, 232, 240))
    text(slide, label.upper(), x + 0.18, y + 0.14, w - 0.36, 0.2, size=8, color=P_MUTED, bold=True)
    text(slide, value, x + 0.18, y + 0.39, w - 0.36, 0.4, size=22, color=color, bold=True)
    if hint: text(slide, hint, x + 0.18, y + 0.84, w - 0.36, 0.16, size=8, color=P_MUTED)


def add_picture(slide, path: Path, x, y, w=None, h=None):
    kwargs = {}
    if w is not None: kwargs["width"] = PInches(w)
    if h is not None: kwargs["height"] = PInches(h)
    return slide.shapes.add_picture(str(path), PInches(x), PInches(y), **kwargs)


def build_pptx() -> None:
    metrics_data = json.loads((ROOT / "models" / "metrics.json").read_text(encoding="utf-8"))
    etl = json.loads((ROOT / "data" / "processed" / "etl_summary.json").read_text(encoding="utf-8"))
    agent_eval = json.loads((ROOT / "reports" / "agent_evaluation.json").read_text(encoding="utf-8"))
    prs = Presentation(); prs.slide_width = PInches(13.333); prs.slide_height = PInches(7.5)

    # 1 cover
    slide = prs.slides.add_slide(prs.slide_layouts[6]); slide.background.fill.solid(); slide.background.fill.fore_color.rgb = P_NAVY
    rect(slide, 0, 0, 0.18, 7.5, P_CYAN, radius=False)
    text(slide, "УПРАВЛЕНИЕ ДАННЫМИ · 09.03.03", 0.75, 0.7, 8.5, 0.3, 11, P_CYAN, True)
    text(slide, "Академический\nнавигатор", 0.75, 1.45, 7.5, 1.65, 34, P_WHITE, True)
    text(slide, "Интеллектуальный агент-аналитик академической\nуспеваемости и риска неуспеваемости", 0.78, 3.25, 7.5, 0.8, 18, PptRGB(203, 213, 225))
    rect(slide, 9.2, 1.05, 3.1, 3.1, PptRGB(23, 37, 84))
    text(slide, "◈", 9.9, 1.38, 1.7, 1.2, 62, P_CYAN, True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    text(slide, "DATA → ACTION", 9.55, 3.2, 2.4, 0.3, 11, P_WHITE, True, align=PP_ALIGN.CENTER)
    text(slide, "Выполнил(а): [Ф. И. О.] · группа ______\nРуководитель: [Ф. И. О.]\n2026", 0.78, 5.75, 7, 0.8, 13, PptRGB(148, 163, 184))

    # 2 problem
    slide = base_slide(prs, "Проблема: данные есть, раннего действия нет", 2)
    rich_lines(slide, ["Деканат, LMS и посещаемость хранят разные фрагменты картины", "Пропуски, дубликаты, разные категории и версии ведомостей", "Позднее обнаружение затруднений сокращает время на поддержку", "Прогноз без объяснения, доступа и аудита создаёт новый риск"], 0.65, 1.65, 6.15, 3.9, 18)
    rect(slide, 7.35, 1.65, 5.3, 3.9, P_NAVY)
    text(slide, "ЦЕЛЕВОЙ СЦЕНАРИЙ", 7.75, 2.05, 4.5, 0.3, 10, P_CYAN, True)
    text(slide, "Оценить риск хотя бы одной\nнеудовлетворительной оценки\nдо итоговой аттестации", 7.75, 2.65, 4.3, 1.7, 25, P_WHITE, True)
    text(slide, "Результат → проверка данных → разговор → поддержка", 7.75, 4.75, 4.15, 0.5, 12, PptRGB(203, 213, 225))
    text(slide, "Не основание для санкций", 0.67, 6.55, 5, 0.3, 12, P_RED, True)

    # 3 goal
    slide = base_slide(prs, "Цель и четыре лабораторных этапа", 3)
    stages = [
        ("01", "Данные", "3 системы · ETL · SQLite · ERD", P_BLUE),
        ("02", "Аналитика", "EDA · 14 признаков · TF-IDF", P_CYAN),
        ("03", "Модель", "baseline · GridSearchCV · test", P_AMBER),
        ("04", "Прототип", "агент · RBAC · Streamlit · logs", P_GREEN),
    ]
    for idx, (num, name, desc, color) in enumerate(stages):
        x = 0.65 + idx * 3.12
        rect(slide, x, 1.7, 2.75, 3.15, P_LIGHT, line=PptRGB(226,232,240))
        text(slide, num, x + 0.2, 1.95, 0.7, 0.42, 22, color, True)
        text(slide, name, x + 0.2, 2.55, 2.3, 0.45, 21, P_NAVY, True)
        text(slide, desc, x + 0.2, 3.3, 2.25, 1.0, 14, P_MUTED)
    text(slide, "Итог: воспроизводимый контур от сырого события до проверяемого ответа", 0.65, 5.65, 12, 0.45, 20, P_NAVY, True, align=PP_ALIGN.CENTER)

    # 4 sources
    slide = base_slide(prs, "Источники и результаты очистки", 4)
    metric(slide, "Студенты", "420", 0.65, 1.55, 2.25)
    metric(slide, "Дисциплины", "6", 3.05, 1.55, 2.25, P_CYAN)
    metric(slide, "Посещения", "30 228", 5.45, 1.55, 2.25, P_AMBER)
    metric(slide, "LMS-события", "44 178", 7.85, 1.55, 2.25, P_GREEN)
    metric(slide, "Проблем качества", "374", 10.25, 1.55, 2.25, P_RED)
    add_picture(slide, FIG / "data_quality.png", 0.85, 3.0, w=6.2)
    rich_lines(slide, ["6 дубликатов студентов", "80 старых версий ведомости", "120 повторных отметок", "100 повторных LMS-событий", "40 аномалий длительности", "0 ошибок внешних ключей"], 7.65, 3.15, 4.8, 2.85, 16)
    text(slide, "15 проверок · каждое действие записано в data_quality_log", 7.65, 6.25, 4.7, 0.35, 12, P_BLUE, True)

    # 5 architecture
    slide = base_slide(prs, "Архитектура: инструменты прежде генерации", 5)
    add_picture(slide, FIG / "architecture.png", 0.55, 1.45, w=12.2)
    text(slide, "LLM не выполняет SQL и не является источником чисел", 0.75, 6.85, 11.8, 0.25, 12, P_RED, True, align=PP_ALIGN.CENTER)

    # 6 DB
    slide = base_slide(prs, "Хранение: нормализованная схема + наблюдаемость", 6)
    add_picture(slide, FIG / "er_diagram.png", 0.62, 1.45, w=8.5)
    rich_lines(slide, ["10 таблиц", "PK / FK / CHECK / UNIQUE", "индексы по студенту, времени и риску", "model_runs связывает версию и метрики", "predictions хранит вероятность и факторы", "query_logs фиксирует задержку и статус"], 9.35, 1.75, 3.25, 3.8, 15)
    text(slide, "PRAGMA foreign_key_check → 0 ошибок", 9.38, 5.9, 3.0, 0.45, 13, P_GREEN, True)

    # 7 EDA
    slide = base_slide(prs, "EDA: целевой класс и ранние индикаторы", 7)
    add_picture(slide, FIG / "target_distribution.png", 0.6, 1.55, w=5.7)
    add_picture(slide, FIG / "risk_scatter.png", 6.45, 1.55, w=6.25)
    metric(slide, "Доля риска", "34,5%", 0.9, 5.95, 2.35, P_RED)
    metric(slide, "Посещаемость", "64,2%", 3.42, 5.95, 2.35, P_BLUE)
    metric(slide, "Промеж. балл", "62,2", 6.72, 5.95, 2.35, P_CYAN)
    metric(slide, "Сдача вовремя", "61,9%", 9.25, 5.95, 2.35, P_GREEN)

    # 8 features
    slide = base_slide(prs, "14 признаков без утечки + текстовый индекс", 8)
    rect(slide, 0.65, 1.55, 5.9, 4.85, P_LIGHT, line=PptRGB(226,232,240))
    text(slide, "СТРУКТУРИРОВАННЫЕ", 0.95, 1.9, 4.8, 0.28, 10, P_BLUE, True)
    rich_lines(slide, ["исторический GPA и вступительный балл", "посещаемость и опоздания", "активные дни и события LMS", "своевременность и тесты", "промежуточные баллы и задания", "число попыток и доля низких результатов"], 0.95, 2.35, 5.1, 3.3, 16)
    rect(slide, 6.8, 1.55, 5.85, 4.85, P_NAVY)
    text(slide, "НЕСТРУКТУРИРОВАННЫЕ", 7.1, 1.9, 4.8, 0.28, 10, P_CYAN, True)
    text(slide, "5 документов", 7.1, 2.45, 2.3, 0.4, 24, P_WHITE, True)
    text(slide, "19 фрагментов", 9.75, 2.45, 2.3, 0.4, 24, P_WHITE, True)
    text(slide, "TF-IDF · уни- и биграммы\nсловарь 701 · cosine similarity", 7.1, 3.35, 4.6, 1.0, 18, PptRGB(203,213,225))
    text(slide, "ИСКЛЮЧЕНЫ ИЗ X", 7.1, 4.85, 4.2, 0.25, 10, P_RED, True)
    text(slide, "final_score · final_grade\nfailed_courses · final_gpa", 7.1, 5.2, 4.8, 0.7, 16, P_WHITE, True)

    # 9 experiment
    slide = base_slide(prs, "Эксперимент: выбор только до просмотра test", 9)
    metric(slide, "Train", "252", 0.75, 1.6, 2.35, P_BLUE, "60%")
    metric(slide, "Validation", "84", 3.25, 1.6, 2.35, P_CYAN, "20%")
    metric(slide, "Test", "84", 5.75, 1.6, 2.35, P_RED, "20% · один раз")
    rect(slide, 8.55, 1.6, 3.95, 1.12, P_NAVY)
    text(slide, "seed 42 · stratified", 8.85, 1.95, 3.35, 0.35, 18, P_WHITE, True, align=PP_ALIGN.CENTER)
    models = [
        ("Dummy", "F1 0,000", "baseline"),
        ("Logistic Regression", "F1 0,853", "validation"),
        ("Random Forest", "F1 0,862", "выбрана"),
    ]
    for idx, (name, val, note) in enumerate(models):
        y = 3.25 + idx * 0.95
        rect(slide, 0.8, y, 11.65, 0.7, P_LIGHT, line=PptRGB(226,232,240))
        text(slide, name, 1.05, y + 0.17, 4.0, 0.3, 17, P_NAVY, True)
        text(slide, val, 6.45, y + 0.17, 2.2, 0.3, 17, P_BLUE if idx<2 else P_GREEN, True)
        text(slide, note, 10.3, y + 0.17, 1.7, 0.3, 12, P_MUTED, True, align=PP_ALIGN.RIGHT)
    text(slide, "GridSearchCV: 12 комбинаций · 4-fold · best depth=4, leaf=5, features=sqrt", 0.8, 6.3, 11.7, 0.35, 13, P_MUTED, align=PP_ALIGN.CENTER)

    # 10 metrics
    slide = base_slide(prs, "Результат на независимой тестовой выборке", 10)
    metric(slide, "F1", "0,877", 0.65, 1.45, 2.2, P_BLUE)
    metric(slide, "Recall", "0,862", 3.0, 1.45, 2.2, P_CYAN)
    metric(slide, "Precision", "0,893", 5.35, 1.45, 2.2, P_GREEN)
    metric(slide, "ROC-AUC", "0,954", 7.7, 1.45, 2.2, P_AMBER)
    metric(slide, "Brier", "0,077", 10.05, 1.45, 2.2, P_RED, "меньше — лучше")
    add_picture(slide, FIG / "confusion_matrix.png", 0.8, 2.95, w=4.85)
    add_picture(slide, FIG / "roc_curve.png", 6.0, 2.95, w=5.9)
    text(slide, "TN 52 · FP 3 · FN 4 · TP 25", 0.85, 6.6, 4.8, 0.3, 12, P_MUTED, True, align=PP_ALIGN.CENTER)
    text(slide, "Метрики синтетические — не внешняя валидация", 6.1, 6.6, 5.7, 0.3, 12, P_RED, True, align=PP_ALIGN.CENTER)

    # 11 interpretation
    slide = base_slide(prs, "Интерпретация: важность ≠ причинность", 11)
    add_picture(slide, FIG / "feature_importance.png", 0.65, 1.45, w=7.45)
    rect(slide, 8.55, 1.65, 3.95, 4.4, P_NAVY)
    text(slide, "ТОП-ФАКТОРЫ", 8.9, 2.0, 3.25, 0.25, 10, P_CYAN, True)
    text(slide, "1", 8.9, 2.55, 0.4, 0.4, 23, P_CYAN, True); text(slide, "балл заданий", 9.5, 2.6, 2.5, 0.3, 17, P_WHITE, True)
    text(slide, "2", 8.9, 3.35, 0.4, 0.4, 23, P_CYAN, True); text(slide, "число попыток", 9.5, 3.4, 2.5, 0.3, 17, P_WHITE, True)
    text(slide, "3", 8.9, 4.15, 0.4, 0.4, 23, P_CYAN, True); text(slide, "попытки тестов", 9.5, 4.2, 2.5, 0.3, 17, P_WHITE, True)
    text(slide, "Локальное объяснение:\nimportance × отклонение от медианы", 8.9, 5.05, 3.0, 0.7, 13, PptRGB(203,213,225))
    text(slide, "Ассоциация помогает выбрать действие, но не доказывает причину", 0.8, 6.55, 11.7, 0.35, 14, P_RED, True, align=PP_ALIGN.CENTER)

    # 12 agent
    slide = base_slide(prs, "Агент: SQL-инструменты, RAG и безопасный fallback", 12)
    flow = [("1", "Намерение"), ("2", "RBAC"), ("3", "SQL / TF-IDF"), ("4", "JSON-контекст"), ("5", "Шаблон / Ollama"), ("6", "Журнал")]
    for idx, (num, label) in enumerate(flow):
        x = 0.55 + idx * 2.1
        rect(slide, x, 1.75, 1.7, 1.2, P_LIGHT, line=PptRGB(226,232,240))
        text(slide, num, x + 0.13, 1.94, 0.35, 0.3, 18, P_BLUE, True)
        text(slide, label, x + 0.45, 2.0, 1.1, 0.5, 13, P_NAVY, True, align=PP_ALIGN.CENTER)
        if idx < 5: text(slide, "→", x + 1.75, 2.08, 0.3, 0.3, 17, P_CYAN, True)
    rect(slide, 0.65, 3.55, 3.75, 2.1, P_NAVY); text(slide, "Студент", 0.95, 3.88, 3.1, 0.35, 21, P_WHITE, True); text(slide, "только своя карточка", 0.95, 4.55, 3.1, 0.3, 15, PptRGB(203,213,225))
    rect(slide, 4.78, 3.55, 3.75, 2.1, PptRGB(23,37,84)); text(slide, "Преподаватель", 5.08, 3.88, 3.1, 0.35, 21, P_WHITE, True); text(slide, "группы и список поддержки", 5.08, 4.55, 3.1, 0.3, 15, PptRGB(203,213,225))
    rect(slide, 8.9, 3.55, 3.75, 2.1, PptRGB(22,78,99)); text(slide, "Деканат", 9.2, 3.88, 3.1, 0.35, 21, P_WHITE, True); text(slide, "агрегаты и журнал", 9.2, 4.55, 3.1, 0.3, 15, PptRGB(203,213,225))
    text(slide, "LLM недоступна? Функции продолжают работать в детерминированном режиме", 0.7, 6.35, 11.9, 0.35, 13, P_GREEN, True, align=PP_ALIGN.CENTER)

    # 13 UI
    slide = base_slide(prs, "Прототип: один интерфейс для решения и аудита", 13)
    tabs = [("✦", "Агент", "чат и источники"), ("◎", "Карточка", "риск и действия"), ("▦", "Дашборд", "группы и фильтры"), ("◫", "Модель", "метрики и ROC"), ("✓", "Данные", "15 проверок")]
    for idx, (icon, name, desc) in enumerate(tabs):
        x = 0.58 + idx * 2.52
        rect(slide, x, 1.55, 2.25, 3.5, P_LIGHT, line=PptRGB(226,232,240))
        text(slide, icon, x + 0.65, 1.9, 0.95, 0.75, 35, P_BLUE if idx<3 else P_CYAN, True, align=PP_ALIGN.CENTER)
        text(slide, name, x + 0.25, 2.9, 1.75, 0.4, 20, P_NAVY, True, align=PP_ALIGN.CENTER)
        text(slide, desc, x + 0.25, 3.55, 1.75, 0.75, 14, P_MUTED, align=PP_ALIGN.CENTER)
    text(slide, "Streamlit + Plotly · SQLite · локальный запуск без платного API", 0.65, 5.65, 12.0, 0.4, 18, P_NAVY, True, align=PP_ALIGN.CENTER)
    text(slide, "Роль в прототипе — демонстрация; продуктивно нужна SSO-аутентификация", 0.65, 6.35, 12.0, 0.3, 12, P_RED, True, align=PP_ALIGN.CENTER)

    # 14 tests
    slide = base_slide(prs, "Проверка: данные, модель, доступ и скорость", 14)
    metric(slide, "Pytest", "9 / 9", 0.65, 1.55, 2.5, P_GREEN, "пройдено")
    metric(slide, "Намерения", "23 / 23", 3.35, 1.55, 2.5, P_BLUE, "контрольный набор")
    metric(slide, "Медиана", f"{agent_eval['latency_ms']['median']:.1f} мс", 6.05, 1.55, 2.5, P_CYAN, "без LLM")
    metric(slide, "P95", f"{agent_eval['latency_ms']['p95']:.1f} мс", 8.75, 1.55, 2.5, P_AMBER, "без UI")
    rich_lines(slide, ["PRAGMA foreign_key_check = 0", "пропуски в признаках = 0", "итоговые поля отсутствуют в X", "вероятности находятся в [0;1]", "чужая карточка для студента → forbidden", "Ollama недоступна → безопасный fallback"], 0.75, 3.25, 5.8, 2.65, 17)
    rect(slide, 7.0, 3.15, 5.55, 2.75, P_NAVY)
    text(slide, "ОГРАНИЧЕНИЕ ОЦЕНКИ", 7.4, 3.55, 4.6, 0.3, 10, P_CYAN, True)
    text(slide, "Контрольные фразы составлены\nразработчиком. Нужен внешний\nнабор реальных формулировок.", 7.4, 4.2, 4.6, 1.2, 20, P_WHITE, True)

    # 15 ethics
    slide = base_slide(prs, "Этика: прогноз инициирует помощь, а не решение", 15)
    risks = [("FP", "необоснованный сигнал", P_AMBER), ("FN", "пропущенная потребность", P_RED), ("DRIFT", "изменение процесса", P_BLUE), ("PRIVACY", "избыточный доступ", P_CYAN)]
    for idx, (tag, desc, color) in enumerate(risks):
        x = 0.65 + idx * 3.08
        rect(slide, x, 1.55, 2.7, 1.35, P_LIGHT, line=PptRGB(226,232,240))
        text(slide, tag, x + 0.2, 1.82, 0.9, 0.3, 16, color, True)
        text(slide, desc, x + 0.2, 2.28, 2.2, 0.35, 12, P_MUTED)
    text(slide, "Human-in-the-loop", 0.7, 3.55, 4.0, 0.5, 28, P_NAVY, True)
    rich_lines(slide, ["проверить исходные данные", "поговорить со студентом", "согласовать действие", "повторить оценку"], 0.75, 4.25, 4.8, 2.0, 17)
    rect(slide, 6.1, 3.4, 6.25, 2.7, P_NAVY)
    text(slide, "Перед реальным пилотом", 6.45, 3.75, 5.5, 0.35, 20, P_WHITE, True)
    text(slide, "правовое основание · DPIA · SSO · шифрование\nвнешняя валидация · fairness · drift · обжалование", 6.45, 4.45, 5.25, 1.0, 17, PptRGB(203,213,225))

    # 16 conclusion
    slide = base_slide(prs, "Результат и развитие", 16)
    text(slide, "Полный цикл реализован", 0.7, 1.55, 5.3, 0.55, 29, P_NAVY, True)
    rich_lines(slide, ["3 источника → очищенная БД", "14 признаков + TF-IDF", "модель с независимым test", "агент с RBAC и инструментами", "дашборд и технические журналы", "воспроизводимый README + tests"], 0.75, 2.4, 5.3, 3.5, 18)
    rect(slide, 6.55, 1.55, 5.85, 4.75, P_NAVY)
    text(slide, "СЛЕДУЮЩИЙ ШАГ", 6.95, 1.95, 4.9, 0.3, 10, P_CYAN, True)
    text(slide, "Временная внешняя\nвалидация на легитимных\nреальных данных", 6.95, 2.7, 4.8, 1.65, 27, P_WHITE, True)
    text(slide, "Затем — оценка не только точности,\nно и полезности мер поддержки", 6.95, 4.9, 4.8, 0.75, 16, PptRGB(203,213,225))
    text(slide, "Спасибо · вопросы?", 0.7, 6.5, 11.7, 0.45, 22, P_BLUE, True, align=PP_ALIGN.CENTER)

    prs.core_properties.title = "Академический навигатор — презентация проекта"
    prs.core_properties.author = "[Ф. И. О. студента]"
    prs.core_properties.subject = "Управление данными"
    prs.save(PPTX_PATH)


def build_speech() -> None:
    text_value = """# Текст выступления (8–10 минут)

## Слайд 1

Здравствуйте. Представляю проект «Академический навигатор» — интеллектуальный агент для раннего выявления риска неуспеваемости. Главная задача работы — показать полный цикл управления данными: от грязных разнородных выгрузок до проверяемого ответа пользователю.

## Слайд 2

Образовательные данные распределены между деканатом, LMS и системой посещаемости. Они имеют разные форматы и дефекты, а проблема часто обнаруживается слишком поздно. Целевой сценарий — до итоговой аттестации оценить риск хотя бы одной неудовлетворительной оценки. Важно: прогноз предназначен для поддержки, а не для санкций.

## Слайд 3

Проект соответствует четырём лабораторным этапам. Сначала сбор, ETL и БД. Затем EDA, признаки и текстовый индекс. На третьем этапе — сравнение моделей и независимая оценка. На четвёртом — агент, интерфейс, дашборд и журналирование.

## Слайд 4

Используются полностью синтетические данные, поэтому репозиторий можно публиковать. После очистки осталось 420 студентов, 2 520 записей успеваемости, 30 228 посещений и 44 178 LMS-событий. ETL обнаружил 374 проблемных значения или строки: дубликаты, старые версии, неизвестные статусы и аномальные длительности. Все действия зафиксированы в журнале качества, ошибок внешних ключей нет.

## Слайды 5–6

Архитектура разделяет источники, ETL, аналитику, модель и продуктовый слой. В SQLite десять таблиц: факты, витрина признаков, версии модели, прогнозы и журналы. Ключевой принцип агента — «инструменты прежде генерации»: языковая модель не пишет SQL и не является источником чисел.

## Слайды 7–8

Целевой класс составляет 34,5 процента. Сформированы 14 ранних признаков: посещаемость, LMS, промежуточные результаты и исторический GPA. Итоговые оценки, число двоек и итоговый GPA исключены из входа, чтобы избежать утечки. Для текстов создан TF-IDF-индекс: пять документов, 19 фрагментов и словарь из 701 термина.

## Слайды 9–10

Данные разделены 60, 20 и 20 процентов. Сравнивались DummyClassifier, логистическая регрессия и Random Forest. Для леса проверено 12 комбинаций в четырёхкратной кросс-валидации. Модель выбрана только по validation, а test использован один раз. На тесте F1 равен 0,877, recall — 0,862, precision — 0,893, ROC-AUC — 0,954. Эти метрики относятся к синтетическому эксперименту.

## Слайд 11

Наиболее значимы баллы заданий, число попыток, попытки тестов и исторический GPA. В карточке показываются приближённые локальные факторы. Они помогают выбрать направление поддержки, но не являются причинным доказательством.

## Слайды 12–13

Агент определяет намерение, проверяет роль, вызывает параметризованный SQL или TF-IDF-поиск, формирует контекст и только затем использует шаблон либо локальную Ollama. Студент видит только собственную карточку. Интерфейс Streamlit объединяет чат, карточку, дашборд, модельные метрики и качество данных.

## Слайд 14

Автоматически пройдено девять тестов. Маршрутизатор правильно определил 23 из 23 контрольных фраз. В локальном шаблонном режиме медианная задержка составила около трёх миллисекунд, P95 — около восемнадцати. Это измерение не включает UI и генерацию LLM.

## Слайд 15

Основные риски — ложные сигналы, пропуски, дрейф и конфиденциальность. Поэтому обязательно участие человека: сначала проверка данных, затем разговор, согласование действия и повторная оценка. Перед реальным пилотом нужны правовое основание, SSO, шифрование, внешняя валидация, fairness и процедура обжалования.

## Слайд 16

Итог: полный жизненный цикл реализован и воспроизводится одной командой. Следующий содержательный шаг — временная внешняя валидация на легитимных данных и оценка того, действительно ли предложенные меры поддержки улучшают результат. Спасибо, готов(а) ответить на вопросы.
"""
    SPEECH_PATH.write_text(text_value, encoding="utf-8")


def main() -> None:
    build_docx()
    build_pptx()
    build_speech()
    print(f"Создано:\n- {DOCX_PATH}\n- {PPTX_PATH}\n- {SPEECH_PATH}")


if __name__ == "__main__":
    main()
