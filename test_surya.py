#!/usr/bin/env python3
"""Quick Surya OCR test on a few scanned PRA documents.

Run with civic_media's python (has GPU torch):
    /path/to/civic_media/venv/Scripts/python.exe test_surya.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "shasta_nextrequest_backup" / "documents"

TEST_FILES = [
    # Contract — main use case
    (DOCS / "25-492" / "C2 Agreement E1 Audiovisusal Tech.pdf", 3),
    # Candidate applications — form-heavy
    (DOCS / "25-891" / "ROV Candidate Applications - Redacted.pdf", 2),
    # Small scanned letters
    (DOCS / "25-821" / "Dist 3.pdf", 2),
]


def extract_pages_as_images(pdf_path: Path, max_pages: int) -> list:
    """Render PDF pages to PIL images using pypdfium2."""
    import pypdfium2 as pdfium
    images = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    n = min(len(pdf), max_pages)
    for i in range(n):
        page = pdf[i]
        bitmap = page.render(scale=2.0)  # 2x = ~144 dpi
        images.append(bitmap.to_pil())
    return images


def test_file(pdf_path: Path, max_pages: int, ocr_predictor, det_predictor):
    """Run Surya on first N pages of a PDF and print results."""
    print(f"\n{'='*70}")
    print(f"FILE: {pdf_path.name}  ({pdf_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Testing first {max_pages} page(s)")
    print("="*70)

    t0 = time.time()
    images = extract_pages_as_images(pdf_path, max_pages)
    print(f"  Rendered {len(images)} pages in {time.time()-t0:.1f}s")

    # Run OCR (pass det_predictor so Surya handles layout detection internally)
    t1 = time.time()
    predictions = ocr_predictor(images, det_predictor=det_predictor)
    elapsed = time.time() - t1
    print(f"  OCR completed in {elapsed:.1f}s")

    for p_idx, pred in enumerate(predictions):
        lines = [line.text for line in pred.text_lines]
        char_count = sum(len(l) for l in lines)
        print(f"\n  --- Page {p_idx + 1} ({len(lines)} lines, {char_count} chars) ---")
        # Print first 30 lines
        for line in lines[:30]:
            print(f"    {line}")
        if len(lines) > 30:
            print(f"    ... ({len(lines) - 30} more lines)")


def main():
    import torch
    print(f"PyTorch: {torch.__version__}  CUDA: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    print("\nLoading Surya models...")
    t0 = time.time()
    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor
    from surya.detection import DetectionPredictor
    foundation = FoundationPredictor()
    rec = RecognitionPredictor(foundation_predictor=foundation)
    det = DetectionPredictor()
    print(f"Models loaded in {time.time()-t0:.1f}s")

    for pdf_path, max_pages in TEST_FILES:
        if not pdf_path.exists():
            print(f"\nSKIP (not found): {pdf_path}")
            continue
        try:
            test_file(pdf_path, max_pages, rec, det)
        except Exception as e:
            print(f"\nERROR on {pdf_path.name}: {e}")
            import traceback
            traceback.print_exc()

    print("\n\nDone.")


if __name__ == "__main__":
    main()
