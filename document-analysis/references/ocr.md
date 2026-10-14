# OCR

OCR is for image-only pages or unusable text extraction, not a default transformation. Preserve the original and write the OCR PDF only inside the analysis directory.

Use `kor+eng` unless the user specifies another language set. Run one OCR job at a time by default. OCRmyPDF performs image preparation and writes a searchable PDF; extract text again from that PDF rather than treating an OCR sidecar as a complete document transcript.

If OCR fails or a page has suspiciously little text, record the page and error in `quality-report.md`. Do not silently invent missing text or retry indefinitely.
