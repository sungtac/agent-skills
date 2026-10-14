# Routing

Run the inspector first. It reports file type, page count, encryption status, text density, and available processors.

| Condition | Primary processor | Additional action |
| --- | --- | --- |
| Text-bearing PDF | Poppler | Use PyMuPDF only if structural detail is requested. |
| PDF needing tables, positions, images, or multi-column analysis | PyMuPDF plus Poppler text | Preserve both outputs when they materially differ. |
| Scanned PDF, no text layer, or implausibly sparse/garbled text | OCRmyPDF with Tesseract `kor+eng` | Re-extract every page from the OCR PDF. |
| DOCX, PPTX, XLSX, email, or another non-PDF document | Apache Tika | Use a format-specific tool only if Tika cannot provide the requested structure. |
| Encrypted, damaged, or unsupported input | None | Report the condition and do not attempt a bypass. |

Use dual extraction only for a requested high-accuracy analysis, an identified discrepancy, or a document whose conclusions have material consequences. It is not the default.
