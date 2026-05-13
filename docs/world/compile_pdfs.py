"""Compile world-building markdown documents to individual PDFs using fpdf2."""

import re
from pathlib import Path
from fpdf import FPDF


class WorldDocPDF(FPDF):
    """Custom PDF class for world-building documents."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)
        # Register Unicode fonts
        font_dir = "C:/Windows/Fonts"
        self.add_font("Arial", "", f"{font_dir}/arial.ttf", uni=True)
        self.add_font("Arial", "B", f"{font_dir}/arialbd.ttf", uni=True)
        self.add_font("Arial", "I", f"{font_dir}/ariali.ttf", uni=True)
        self.add_font("Arial", "BI", f"{font_dir}/arialbi.ttf", uni=True)
        self.add_font("CourierNew", "", f"{font_dir}/cour.ttf", uni=True)

    def header(self):
        self.set_font("Arial", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, "LLM Firm Lab — Senolytic Regenerative Therapy World", align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def add_title(self, title: str):
        self.set_font("Arial", "B", 18)
        self.set_text_color(0, 51, 102)
        self.multi_cell(0, 10, title)
        self.ln(4)
        # Horizontal rule
        self.set_draw_color(0, 51, 102)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def add_heading2(self, text: str):
        self.ln(4)
        self.set_font("Arial", "B", 14)
        self.set_text_color(0, 51, 102)
        self.multi_cell(0, 8, text)
        self.ln(2)

    def add_heading3(self, text: str):
        self.ln(3)
        self.set_font("Arial", "B", 11)
        self.set_text_color(51, 51, 51)
        self.multi_cell(0, 7, text)
        self.ln(1)

    def add_heading4(self, text: str):
        self.ln(2)
        self.set_font("Arial", "BI", 10)
        self.set_text_color(51, 51, 51)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def add_paragraph(self, text: str):
        self.set_font("Arial", "", 10)
        self.set_text_color(0, 0, 0)
        # Handle bold and italic inline
        text = text.strip()
        if text:
            self.multi_cell(0, 5, text)
            self.ln(2)

    def add_bullet(self, text: str, indent: int = 0):
        self.set_font("Arial", "", 10)
        self.set_text_color(0, 0, 0)
        x = self.l_margin + 5 + indent * 5
        self.set_x(x)
        bullet = "\u2022 "
        w = self.w - x - self.r_margin
        self.multi_cell(w, 5, bullet + text.strip())
        self.ln(1)

    def add_code_block(self, text: str):
        self.set_font("CourierNew", "", 9)
        self.set_text_color(51, 51, 51)
        self.set_fill_color(240, 240, 240)
        x = self.l_margin + 5
        self.set_x(x)
        w = self.w - x - self.r_margin
        for line in text.split("\n"):
            self.set_x(x)
            self.cell(w, 5, line, fill=True)
            self.ln()
        self.ln(2)

    def add_table(self, headers: list[str], rows: list[list[str]]):
        """Add a simple table."""
        self.set_font("Arial", "", 8)
        n_cols = len(headers)
        available = self.w - self.l_margin - self.r_margin - 5
        col_w = available / n_cols

        # Header
        self.set_font("Arial", "B", 8)
        self.set_fill_color(0, 51, 102)
        self.set_text_color(255, 255, 255)
        x_start = self.l_margin + 2.5
        self.set_x(x_start)
        for h in headers:
            self.cell(col_w, 6, h[:int(col_w / 1.8)], border=1, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Arial", "", 8)
        self.set_text_color(0, 0, 0)
        for i, row in enumerate(rows):
            if i % 2 == 0:
                self.set_fill_color(245, 245, 245)
            else:
                self.set_fill_color(255, 255, 255)
            self.set_x(x_start)
            for cell in row:
                self.cell(col_w, 5, cell[:int(col_w / 1.8)], border=1, fill=True)
            self.ln()
        self.ln(3)


def clean_md_formatting(text: str) -> str:
    """Remove markdown bold/italic markers for plain text output."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def parse_table(lines: list[str], start_idx: int) -> tuple[list[str], list[list[str]], int]:
    """Parse a markdown table starting at start_idx. Returns headers, rows, end_idx."""
    header_line = lines[start_idx].strip()
    headers = [h.strip() for h in header_line.split("|") if h.strip()]

    # Skip separator line
    idx = start_idx + 2
    rows = []
    while idx < len(lines) and "|" in lines[idx] and lines[idx].strip().startswith("|"):
        cells = [c.strip() for c in lines[idx].split("|") if c.strip()]
        # Pad or truncate to match header count
        while len(cells) < len(headers):
            cells.append("")
        cells = cells[: len(headers)]
        rows.append(cells)
        idx += 1
    return headers, rows, idx


def md_to_pdf(md_path: Path, pdf_path: Path):
    """Convert a markdown file to PDF."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    pdf = WorldDocPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    i = 0
    in_code_block = False
    code_lines = []

    while i < len(lines):
        line = lines[i]

        # Code block toggle
        if line.strip().startswith("```"):
            if in_code_block:
                pdf.add_code_block("\n".join(code_lines))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            pdf.set_draw_color(200, 200, 200)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
            i += 1
            continue

        # Headers
        if stripped.startswith("# ") and not stripped.startswith("## "):
            pdf.add_title(clean_md_formatting(stripped[2:]))
            i += 1
            continue
        if stripped.startswith("## "):
            pdf.add_heading2(clean_md_formatting(stripped[3:]))
            i += 1
            continue
        if stripped.startswith("### "):
            pdf.add_heading3(clean_md_formatting(stripped[4:]))
            i += 1
            continue
        if stripped.startswith("#### "):
            pdf.add_heading4(clean_md_formatting(stripped[5:]))
            i += 1
            continue

        # Table
        if "|" in stripped and stripped.startswith("|"):
            # Check if next line is separator
            if i + 1 < len(lines) and re.match(r"\s*\|[\s\-:|]+\|", lines[i + 1]):
                headers, rows, end_idx = parse_table(lines, i)
                headers = [clean_md_formatting(h) for h in headers]
                rows = [[clean_md_formatting(c) for c in r] for r in rows]
                pdf.add_table(headers, rows)
                i = end_idx
                continue

        # Bullet points
        if stripped.startswith("- ") or stripped.startswith("* "):
            indent = (len(line) - len(line.lstrip())) // 2
            pdf.add_bullet(clean_md_formatting(stripped[2:]), indent)
            i += 1
            continue

        # Numbered list
        m = re.match(r"(\d+)\.\s+(.*)", stripped)
        if m:
            pdf.add_bullet(clean_md_formatting(m.group(2)))
            i += 1
            continue

        # Regular paragraph — collect consecutive lines
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if (
                not next_line
                or next_line.startswith("#")
                or next_line.startswith("-")
                or next_line.startswith("*")
                or next_line.startswith("|")
                or next_line.startswith("```")
                or re.match(r"\d+\.\s+", next_line)
            ):
                break
            para_lines.append(next_line)
            i += 1
        pdf.add_paragraph(clean_md_formatting(" ".join(para_lines)))

    pdf.output(str(pdf_path))
    print(f"  Created: {pdf_path.name}")


def main():
    world_dir = Path(__file__).parent
    pdf_dir = world_dir / "pdf"
    pdf_dir.mkdir(exist_ok=True)

    md_files = sorted(world_dir.glob("[0-9]*.md"))
    print(f"Found {len(md_files)} markdown files to compile.\n")

    for md_file in md_files:
        pdf_name = md_file.stem + ".pdf"
        pdf_path = pdf_dir / pdf_name
        print(f"Compiling {md_file.name}...")
        try:
            md_to_pdf(md_file, pdf_path)
        except Exception as e:
            print(f"  ERROR: {e!r}")

    print(f"\nDone. PDFs written to: {pdf_dir}")


if __name__ == "__main__":
    main()
