# OCR for Billing PDFs

## Purpose

Some billing PDFs are scanned or image-only. They look normal in a PDF viewer but contain no extractable text.  
For these files, do not send raw OCR text directly to `markitdown`. Generate a searchable PDF first, then run `markitdown` on that PDF.

## Install OCR Tooling

Recommended toolchain for this skill:

- `ocrmypdf` for generating a searchable PDF in one step
- `tesseract` language data for `eng` and `chi_sim`
- `Ghostscript` where the platform packaging path still requires it

Before running OCR, verify all required executables are present:

```bash
ocrmypdf --version
tesseract --list-langs
gs --version
```

If `eng` is missing, OCR is not ready. If the bill may contain Chinese, `chi_sim` must also appear in `tesseract --list-langs`.

### macOS

Recommended install path:

```bash
brew install ocrmypdf tesseract ghostscript
brew install tesseract-lang
ocrmypdf --version
tesseract --list-langs
gs --version
```

Notes:

- Homebrew's `ocrmypdf` install includes the main OCR stack and recommended dependencies
- Homebrew's `tesseract` formula currently ships only `eng`, `osd`, and `snum` by default, so install `tesseract-lang` when you need `chi_sim`
- After installation, confirm that `eng` and `chi_sim` both appear in `tesseract --list-langs`

### Ubuntu / Debian

Recommended install path:

```bash
sudo apt update
sudo apt install -y ocrmypdf ghostscript tesseract-ocr-eng tesseract-ocr-chi-sim
ocrmypdf --version
tesseract --list-langs
gs --version
```

Notes:

- `ocrmypdf` is available directly from Debian and Ubuntu packages
- Tesseract language packages on Debian-family systems use names like `tesseract-ocr-<langcode>`
- To inspect more language packs, run `apt-cache search tesseract-ocr`

### Windows

Recommended native Windows install path:

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id UB-Mannheim.TesseractOCR
py -m pip install ocrmypdf
py -m ocrmypdf --version
tesseract --list-langs
```

Notes:

- OCRmyPDF's current Windows documentation says `Ghostscript` still needs to be installed manually from the official download page because automated install is no longer supported there
- After installing Ghostscript on Windows, verify the CLI that OCRmyPDF uses is callable from `PATH`
- If `chi_sim` is missing after Tesseract installation, download `chi_sim.traineddata` from the official `tesseract-ocr/tessdata` repository and place it in `C:\\Program Files\\Tesseract-OCR\\tessdata`
- If you prefer a Linux-like package flow on Windows, install Ubuntu 22.04 in WSL first and then use the Ubuntu / Debian commands above inside WSL

## Recommended Command Path

When the source PDF is scanned, image-only, or direct `markitdown` extraction is obviously partial, use forced OCR as the default OCR mode for this workflow:

```bash
ocrmypdf --force-ocr --deskew --rotate-pages -l chi_sim+eng input.pdf output/billing_searchable.pdf
markitdown output/billing_searchable.pdf > output/billing_raw.md
```

This skill defaults to `--force-ocr` once it enters the OCR branch because billing PDFs often contain vector pages that ordinary OCRmyPDF passes will skip, leaving `markitdown` with only partial summary-page extraction.

If `ocrmypdf` is unavailable, fall back to the manual page-image plus `tesseract ... pdf` workflow below.

## Extraction Quality Gate

Do not treat `markitdown` as successful just because the output file is non-empty.

Treat the extraction as insufficient and continue to OCR or forced OCR if any of these are true:

- The Markdown contains only the bill cover page, totals, or account summary
- The file is suspiciously short for the page count, for example only a few KB for a many-page bill
- Detailed usage lines, quantities, per-service sections, or region clues are missing
- The searchable PDF exists, but `markitdown` still appears to capture only the first page

Minimum acceptance before continuing:

- Multiple service or product sections are present
- Detailed usage or pricing lines are present, not only top-level totals
- Region, quantity, amount, or SKU-like strings appear in the extracted text
- The content clearly extends beyond the first summary page

## Required Flow

```text
original scanned PDF
  -> render each page to an image
  -> run Tesseract OCR on each page image
  -> export a searchable PDF with the page image as background
  -> run markitdown on the searchable PDF
  -> output/billing_raw.md
```

## How It Works

### 1. Render each PDF page to an image

Use page images to preserve the original visual layout.

Requirements:

- Keep the original page order
- Use `200-300 DPI`
- Do not crop, reorder, or redraw the page

### 2. Run Tesseract on each page image

Tesseract should detect both text content and its page position.  
The position data is required because the recognized text must be placed back onto the page in the correct coordinates.

### 3. Export a searchable PDF

Tesseract PDF output should contain:

- The original page image as the visual background
- A text layer placed at the recognized coordinates

The result should still look like the original scan, but it must now support search, copy, and text extraction.

## Why This Is Required

Pure OCR text output is not enough for this workflow:

- It loses page structure
- Tables and amounts are easier to scramble
- `markitdown` works better on a PDF that already has a text layer

The input to `markitdown` should therefore be the OCR-generated searchable PDF, not the original scanned PDF and not a standalone OCR text dump.

## Example Command Shape

For a single page image:

```bash
tesseract page-001.png page-001 -l chi_sim+eng pdf
```

This produces:

```text
page-001.pdf
```

For multi-page files:

1. Render the source PDF into page images
2. Run `tesseract ... pdf` for each page
3. Merge the per-page PDFs into one searchable PDF
4. Run `markitdown` on the merged PDF

## Expected Outputs

- `output/billing_searchable.pdf`
- `output/billing_raw.md`

## Acceptance Criteria

`billing_searchable.pdf` should:

- Match the original scanned bill visually
- Allow text selection in a PDF viewer
- Support search for service names, regions, and amounts
- Produce substantial line-item output when passed to `markitdown`, not only a summary page

## Scope in This Skill

This skill keeps only one OCR path:

```text
original PDF -> searchable PDF -> markitdown
```

It does not use a pure-text OCR path before `markitdown`.
