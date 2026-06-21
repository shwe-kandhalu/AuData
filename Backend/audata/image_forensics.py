import sys
from pathlib import Path
from itertools import combinations

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import imagehash


def extract_images_from_pdf(pdf_path: str, output_dir: str = "image_auditor_output/raw_figures"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    figures = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            ext = base_image["ext"]

            image_path = output_dir / f"page_{page_idx + 1}_figure_{img_idx + 1}.{ext}"

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            figures.append({
                "page": page_idx + 1,
                "figure_index": img_idx + 1,
                "path": str(image_path),
            })

    return figures


def split_figure_into_panels(figure_path: str, output_dir: str = "image_auditor_output/panels"):
    """
    Splits a full figure into visually separated panels using whitespace / contour detection.
    This is a practical hackathon-level panel splitter.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(figure_path)
    if img is None:
        return []

    original = img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Threshold white background
    _, thresh = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)

    # Connect nearby content so each panel becomes one region
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 35))
    dilated = cv2.dilate(thresh, kernel, iterations=2)

    contours, _ = cv2.findContours(
        dilated,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    h, w = gray.shape
    panels = []

    for idx, contour in enumerate(contours):
        x, y, pw, ph = cv2.boundingRect(contour)

        # Remove tiny text/noise boxes
        if pw < 120 or ph < 120:
            continue

        # Remove boxes that are almost the full figure
        if pw > 0.95 * w and ph > 0.95 * h:
            continue

        pad = 10
        x1 = max(x - pad, 0)
        y1 = max(y - pad, 0)
        x2 = min(x + pw + pad, w)
        y2 = min(y + ph + pad, h)

        panel_img = original[y1:y2, x1:x2]

        figure_stem = Path(figure_path).stem
        panel_path = output_dir / f"{figure_stem}_panel_{idx + 1}.png"
        cv2.imwrite(str(panel_path), panel_img)

        panels.append({
            "source_figure": figure_path,
            "panel_path": str(panel_path),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "width": int(x2 - x1),
            "height": int(y2 - y1),
        })

    # Sort top-to-bottom, left-to-right
    panels.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]))

    return panels


def is_probably_chart_or_layout(panel_path: str):
    """
    Filters out bar charts / text-heavy panels.
    Western blots and microscopy images usually have fewer sharp graph axes/text elements.
    This is heuristic, not perfect.
    """
    img = cv2.imread(panel_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return True

    edges = cv2.Canny(img, 80, 180)
    edge_density = np.mean(edges > 0)

    # Bar charts / axes / text-heavy panels often have high edge density
    return edge_density > 0.12


def detect_duplicate_panels(panels, threshold=6):
    """
    Compares panel-level images, not whole figures.
    Lower threshold = stricter.
    """
    hashes = {}

    for panel in panels:
        path = panel["panel_path"]

        if is_probably_chart_or_layout(path):
            # Skip likely charts for now
            continue

        try:
            img = Image.open(path).convert("L").resize((256, 256))
            hashes[path] = imagehash.phash(img)
        except Exception as e:
            print(f"Skipping {path}: {e}")

    findings = []

    for path_a, path_b in combinations(hashes.keys(), 2):
        distance = hashes[path_a] - hashes[path_b]
        similarity = round(1 - distance / 64, 3)

        if distance <= threshold:
            findings.append({
                "flag_type": "possible_panel_reuse",
                "panel_a": path_a,
                "panel_b": path_b,
                "hash_distance": int(distance),
                "similarity_score": similarity,
                "severity": "high" if distance <= 3 else "moderate",
            })

    findings.sort(key=lambda x: x["hash_distance"])
    return findings


def run_image_auditor(pdf_path: str):
    print(f"Reading PDF: {pdf_path}")

    figures = extract_images_from_pdf(pdf_path)
    print(f"Extracted full figures/images: {len(figures)}")

    all_panels = []

    for fig in figures:
        panels = split_figure_into_panels(fig["path"])
        all_panels.extend(panels)

    print(f"Extracted subpanels: {len(all_panels)}")

    findings = detect_duplicate_panels(all_panels)
    print(f"Suspicious panel duplicate pairs: {len(findings)}")

    for f in findings[:10]:
        print("\nPossible panel reuse")
        print(f"Panel A: {f['panel_a']}")
        print(f"Panel B: {f['panel_b']}")
        print(f"Hash distance: {f['hash_distance']}")
        print(f"Similarity score: {f['similarity_score']}")
        print(f"Severity: {f['severity']}")

    return {
        "figures": figures,
        "panels": all_panels,
        "findings": findings,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Backend/audata/image_forensics_test.py path/to/paper.pdf")
        sys.exit(1)

    run_image_auditor(sys.argv[1])