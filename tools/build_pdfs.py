# -*- coding: utf-8 -*-
"""Génère les guides PDF (français et anglais) à partir des fichiers Markdown, avec Chrome sans écran."""
import re, subprocess, sys, tempfile
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parent.parent
V = re.search(r'^VERSION = "(.+)"', (ROOT / "rotorweb/server.py").read_text(), re.M).group(1)
DOCS = [("README.md", f"GUIDE-RotorWeb-v{V}-FR.pdf", "fr"), ("README.en.md", f"GUIDE-RotorWeb-v{V}-EN.pdf", "en"),
        ("docs/MISE-A-JOUR-FR.md", f"MISE-A-JOUR-RotorWeb-v{V}-FR.pdf", "fr"), ("docs/UPDATE-EN.md", f"UPDATE-RotorWeb-v{V}-EN.pdf", "en")]
CSS = """@page{size:Letter;margin:16mm 15mm 18mm}
body{font:10.5pt/1.5 'DejaVu Sans',Arial,sans-serif;color:#1b2430}
h1{font-size:21pt;color:#0f4c9c;border-bottom:3px solid #2f81f7;padding-bottom:6px;margin:0 0 14px}
h2{font-size:14pt;color:#0f4c9c;margin:20px 0 8px;page-break-after:avoid;border-bottom:1px solid #d6dfeb;padding-bottom:3px}
h3{font-size:11.5pt;margin:14px 0 6px;page-break-after:avoid}
code{font:9pt 'DejaVu Sans Mono',monospace;background:#eef2f7;padding:1px 4px;border-radius:3px}
pre{background:#0e1319;color:#e6edf3;padding:10px 12px;border-radius:6px;font-size:8.8pt;line-height:1.4;page-break-inside:avoid;white-space:pre-wrap}
pre code{background:none;color:inherit;padding:0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:9.5pt;page-break-inside:avoid}
th,td{border:1px solid #c8d3e1;padding:4px 7px;text-align:left;vertical-align:top}th{background:#e8f0fb}
blockquote{border-left:4px solid #2f81f7;background:#f2f7fe;margin:8px 0;padding:6px 12px}
li{margin:2px 0}"""

COVER_CSS = """@page{size:Letter;margin:0}html,body{margin:0;padding:0}
.c{position:relative;width:8.5in;height:11in;overflow:hidden;background:#0b1220}
.c img{width:100%;height:100%;object-fit:cover;display:block}
.v{position:absolute;left:0;right:0;top:2.42in;text-align:center;font:600 15pt 'DejaVu Sans',Arial,sans-serif;
color:#9fb7d6;letter-spacing:.04em}"""


def chrome_pdf(html, out):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
    subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={out}", f"file://{f.name}"],
                   check=True, capture_output=True)


def cover_pdf(lang, out):
    """Page couverture (logo/couvertures/couverture-xx-200ppp.jpg) + numéro de version."""
    img = ROOT / "logo" / "couvertures" / f"couverture-{lang}-200ppp.jpg"
    if not img.exists():
        return False
    html = (f'<!doctype html><html><head><meta charset="utf-8"><style>{COVER_CSS}</style></head><body>'
            f'<div class="c"><img src="file://{img}"><div class="v">Version {V}</div></div></body></html>')
    chrome_pdf(html, out)
    return True


def build(src, out, lang):
    md = (ROOT / src).read_text(encoding="utf-8")
    # la bannière GitHub du README n'a pas sa place dans le PDF (il a sa couverture)
    md = re.sub(r"(?m)^.*logo/banniere[^\n]*\n", "", md)
    # une liste qui suit directement une ligne de texte : il faut une ligne vide avant
    md = re.sub(r"(?m)^([^\n\-*\d\s|>`#][^\n]*)\n(- |\d+\. )", r"\1\n\n\2", md)
    # blocs de code indentés dans les listes : on les sort de la liste pour qu'ils restent des blocs
    md = re.sub(r"(?ms)^( {2,4})```(\w*)\n(.*?)^\1```", lambda m: "\n```" + m.group(2) + "\n" +
                re.sub(r"(?m)^" + m.group(1), "", m.group(3)) + "```\n", md)
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    # liste numérotée coupée par un bloc de code : la numérotation continue
    parts = re.split(r"(<ol>.*?</ol>)", body, flags=re.S)
    n_prev, html_parts = 0, []
    for i, part in enumerate(parts):
        if part.startswith("<ol>"):
            between = parts[i - 1] if i else ""
            cont = n_prev and re.fullmatch(r"\s*(?:<pre>.*?</pre>\s*)+", between, re.S)
            start = n_prev + 1 if cont else 1
            if cont:
                part = part.replace("<ol>", f'<ol start="{start}">', 1)
            n_prev = start - 1 + part.count("<li>")
        elif not re.fullmatch(r"\s*(?:<pre>.*?</pre>\s*)+", part, re.S):
            n_prev = 0
        html_parts.append(part)
    body = "".join(html_parts)
    html = f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'
    body_pdf = Path(tempfile.mktemp(suffix=".pdf"))
    cov_pdf = Path(tempfile.mktemp(suffix=".pdf"))
    chrome_pdf(html, body_pdf)
    if cover_pdf(lang, cov_pdf):
        from pypdf import PdfWriter
        w = PdfWriter()
        w.append(str(cov_pdf))
        w.append(str(body_pdf))
        w.compress_identical_objects()
        with open(ROOT / out, "wb") as f:
            w.write(f)
    else:
        print("  (couverture absente : logo/couvertures/)", file=sys.stderr)
        body_pdf.replace(ROOT / out)
    print(out)

if __name__ == "__main__":
    for s, o, l in DOCS:
        build(s, o, l)
