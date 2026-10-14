# PDF extraction

Use Poppler for the baseline plain-text artifact. Use `-layout` only when approximate visual column spacing is useful; it is not a substitute for table extraction.

Use PyMuPDF when the request needs text blocks, coordinates, fonts, embedded images, or detected tables. PyMuPDF output is supplementary: retain the Poppler output as the searchable baseline unless inspection shows Poppler is unusable.

For a high-accuracy request, compare page count and per-page text presence between outputs. Investigate only material discrepancies; do not claim semantic equivalence solely from similar character counts.
