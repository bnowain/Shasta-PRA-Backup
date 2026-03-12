#!/usr/bin/env python3
"""Surya OCR worker — runs in civic_media's Python 3.11 venv (GPU torch).

Reads a JSON request from stdin, writes a JSON response to stdout.

Input (stdin):
    {
        "images": [
            {"path": "/abs/path/to/image.png"},          # standalone image file
            {"pdf_path": "/abs/path/to/doc.pdf", "page": 3}  # PDF page by index
        ]
    }

Output (stdout):
    {
        "results": ["text for image 0", "text for image 1", ...]
        "error": null   (or error string)
    }

Run via:
    civic_media/venv/Scripts/python.exe scripts/surya_worker.py
"""

import json
import sys


def render_pdf_page(pdf_path: str, page_index: int):
    """Render a single PDF page to a PIL Image using PyMuPDF."""
    import fitz
    from PIL import Image
    with fitz.open(pdf_path) as doc:
        if page_index >= len(doc):
            return None
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(2, 2))
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def main():
    try:
        request = json.loads(sys.stdin.read())
        image_specs = request.get("images", [])

        if not image_specs:
            print(json.dumps({"results": [], "error": None}))
            return

        # Load images
        from PIL import Image
        images = []
        for spec in image_specs:
            if "pdf_path" in spec:
                img = render_pdf_page(spec["pdf_path"], spec.get("page", 0))
                images.append(img)
            elif "path" in spec:
                img = Image.open(spec["path"]).convert("RGB")
                images.append(img)
            else:
                images.append(None)

        # Filter out any None (failed renders) but track positions
        valid = [(i, img) for i, img in enumerate(images) if img is not None]
        results = [""] * len(images)

        if valid:
            valid_indices, valid_images = zip(*valid)

            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor
            from surya.detection import DetectionPredictor

            foundation = FoundationPredictor()
            rec = RecognitionPredictor(foundation_predictor=foundation)
            det = DetectionPredictor()

            predictions = rec(list(valid_images), det_predictor=det)

            for idx, pred in zip(valid_indices, predictions):
                results[idx] = "\n".join(line.text for line in pred.text_lines)

        print(json.dumps({"results": results, "error": None}))

    except Exception as e:
        import traceback
        print(json.dumps({"results": [], "error": str(e), "traceback": traceback.format_exc()}))


if __name__ == "__main__":
    main()
