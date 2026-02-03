from __future__ import annotations

from pathlib import Path


def render_markdown_to_pdf(markdown_text: str, output_path: Path) -> None:
    from markdown import markdown  # lazy import

    html_body = markdown(markdown_text, output_format="html5")
    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <style>
    body {{ font-family: Georgia, 'Times New Roman', serif; line-height: 1.6; }}
    h1, h2, h3 {{ margin-top: 1.2em; }}
    code, pre {{ font-family: 'Courier New', monospace; }}
    pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; }}
  </style>
</head>
<body>
{html_body}
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer weasyprint, fallback to xhtml2pdf for environments without full deps.
    try:
        from weasyprint import HTML  # type: ignore

        HTML(string=html).write_pdf(str(output_path))
        return
    except Exception:
        pass

    from xhtml2pdf import pisa  # type: ignore

    with output_path.open("wb") as handle:
        result = pisa.CreatePDF(html, dest=handle)
    if result.err:
        raise RuntimeError("PDF export failed via fallback renderer")
