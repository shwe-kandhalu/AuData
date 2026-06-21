from pathlib import Path
from itertools import combinations
from typing import Dict, List, Any

import fitz  # PyMuPDF
from PIL import Image
import imagehash


def extract_images_from_pdf(pdf_path: str, output_dir: str) -> List[Dict[str, Any]]:
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    extracted = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            ext = base_image["ext"]

            image_path = output_dir / f"page_{page_idx + 1}_image_{img_idx + 1}.{ext}"

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            extracted.append({
                "page": page_idx + 1,
                "image_index": img_idx + 1,
                "path": str(image_path),
            })

    return extracted


def detect_duplicate_images(images: List[Dict[str, Any]], threshold: int = 8):
    hashes = {}

    for img in images:
        path = img["path"]
        try:
            pil_img = Image.open(path).convert("L").resize((256, 256))
            hashes[path] = imagehash.phash(pil_img)
        except Exception as e:
            print(f"Skipping image {path}: {e}")

    findings = []

    for path_a, path_b in combinations(hashes.keys(), 2):
        distance = hashes[path_a] - hashes[path_b]
        similarity = round(1 - distance / 64, 3)

        if distance <= threshold:
            findings.append({
                "flag_type": "possible_image_reuse",
                "image_a": path_a,
                "image_b": path_b,
                "hash_distance": int(distance),
                "similarity_score": similarity,
                "severity": "high" if distance <= 4 else "moderate",
                "review_note": (
                    "Two extracted figure images show high perceptual similarity. "
                    "This may indicate duplicated or reused biomedical figure content."
                ),
            })

    findings.sort(key=lambda x: x["hash_distance"])
    return findings


def run_image_auditor(pdf_path: str, session_id: str = "default"):
    output_dir = f"storage/image_forensics/{session_id}"

    images = extract_images_from_pdf(pdf_path, output_dir)
    findings = detect_duplicate_images(images)

    return {
        "agent": "image_auditor",
        "pdf_path": pdf_path,
        "num_images_extracted": len(images),
        "num_findings": len(findings),
        "extracted_images": images,
        "findings": findings[:10],
    }