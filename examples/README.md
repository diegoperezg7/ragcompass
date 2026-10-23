# Sample corpus

`corpus/` is a small, mixed corpus for trying ragcompass and for the test suite. Every file is
synthetic and written for this repository: Halden Instruments, its products, customers and
addresses are fictional. The sample files are released under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

| File | What it exercises |
|---|---|
| `hx200-maintenance-manual.pdf` | Text PDF: headings by font size, two ruled tables, lists, one figure |
| `scanned-invoice.pdf` | Image-only PDF without a text layer, which should be routed to OCR |
| `politica-devoluciones.docx` | Spanish Word document: heading styles, numbered list, table, picture |
| `onboarding-handbook.md` | Markdown with a heading hierarchy, a table, lists and a code fence |
| `hx200-faq.html` | HTML with navigation, script and footer that must be stripped |
| `product-catalog.csv` | 40 rows dense in SKUs, prices and dates (signals for hybrid search) |
| `warehouse-stock.xlsx` | Workbook with two sheets |
| `ticket_export.py` | Source code |
| `wiring-diagram.png` | Image that needs a vision model |

Regenerate it with:

```bash
uv run python examples/generate.py
```
