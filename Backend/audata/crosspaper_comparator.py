import sys
from pathlib import Path
from itertools import product

import fitz  # PyMuPDF
from PIL import Image
import imagehash


IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"]


def extract_images_from_pdf(pdf_path, output_dir, label):
    """
    Extract embedded images from a PDF into an output folder.
    This extracts embedded PDF images, not perfect biological subpanels yet.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_paths = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        images = page.get_images(full=True)

        for img_idx, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            ext = base_image["ext"]

            image_path = output_dir / f"{label}_{pdf_path.stem}_page_{page_idx + 1}_image_{img_idx + 1}.{ext}"

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            image_paths.append(str(image_path))

    return image_paths


def phash_image(path):
    img = Image.open(path).convert("L").resize((256, 256))
    return imagehash.phash(img)


def compare_image_paths(paper_a_images, paper_b_images, threshold=8):
    """
    Compare every extracted image from Paper A against every extracted image from Paper B.
    Lower hash distance means higher similarity.
    """
    print(f"Comparing {len(paper_a_images)} Paper A images against {len(paper_b_images)} Paper B images")
    print(f"Total pairwise comparisons: {len(paper_a_images) * len(paper_b_images)}")

    hash_a = {}
    hash_b = {}

    for path in paper_a_images:
        try:
            hash_a[str(path)] = phash_image(path)
        except Exception as e:
            print(f"Skipping Paper A image due to error: {path} | {e}")

    for path in paper_b_images:
        try:
            hash_b[str(path)] = phash_image(path)
        except Exception as e:
            print(f"Skipping Paper B image due to error: {path} | {e}")

    print(f"Hashable Paper A images: {len(hash_a)}")
    print(f"Hashable Paper B images: {len(hash_b)}")

    findings = []
    closest_pairs = []

    for a, b in product(hash_a.keys(), hash_b.keys()):
        distance = hash_a[a] - hash_b[b]
        similarity = round(1 - distance / 64, 3)

        pair = {
            "flag_type": "possible_cross_paper_figure_reuse",
            "paper_a_figure": a,
            "paper_b_figure": b,
            "hash_distance": int(distance),
            "similarity_score": similarity,
            "severity": "high" if distance <= 4 else "moderate",
        }

        closest_pairs.append(pair)

        if distance <= threshold:
            findings.append(pair)

    findings.sort(key=lambda x: x["hash_distance"])
    closest_pairs.sort(key=lambda x: x["hash_distance"])

    print("\nClosest pairs, regardless of threshold:")
    for pair in closest_pairs[:5]:
        print(
            f"distance={pair['hash_distance']} similarity={pair['similarity_score']} | "
            f"A={Path(pair['paper_a_figure']).name} | B={Path(pair['paper_b_figure']).name}"
        )

    return findings


def compare_two_pdfs(paper_a_pdf, paper_b_pdf, output_root="cross_paper_output", threshold=8):
    """
    Full Part B workflow:

    Paper A PDF -> extract figures
    Paper B PDF -> extract figures
    Compare extracted figures across papers
    Return possible cross-paper reuse findings
    """
    paper_a_pdf = Path(paper_a_pdf)
    paper_b_pdf = Path(paper_b_pdf)
    output_root = Path(output_root)

    # Important: use separate A/B folders even when the same PDF is passed twice.
    # Otherwise the same file stem can overwrite outputs.
    paper_a_dir = output_root / f"paper_A_{paper_a_pdf.stem}_figures"
    paper_b_dir = output_root / f"paper_B_{paper_b_pdf.stem}_figures"

    print(f"Extracting figures from Paper A: {paper_a_pdf}")
    paper_a_images = extract_images_from_pdf(paper_a_pdf, paper_a_dir, label="A")
    print(f"Paper A extracted images: {len(paper_a_images)}")

    print(f"Extracting figures from Paper B: {paper_b_pdf}")
    paper_b_images = extract_images_from_pdf(paper_b_pdf, paper_b_dir, label="B")
    print(f"Paper B extracted images: {len(paper_b_images)}")

    if not paper_a_images:
        print("WARNING: No embedded images were extracted from Paper A.")
    if not paper_b_images:
        print("WARNING: No embedded images were extracted from Paper B.")

    print("Comparing Paper A figures against Paper B figures...")
    findings = compare_image_paths(
        paper_a_images=paper_a_images,
        paper_b_images=paper_b_images,
        threshold=threshold,
    )

    return {
        "paper_a_pdf": str(paper_a_pdf),
        "paper_b_pdf": str(paper_b_pdf),
        "paper_a_output_dir": str(paper_a_dir),
        "paper_b_output_dir": str(paper_b_dir),
        "num_paper_a_images": len(paper_a_images),
        "num_paper_b_images": len(paper_b_images),
        "num_findings": len(findings),
        "findings": findings,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python Backend/audata/crosspaper_comparator.py paper_A.pdf paper_B.pdf [threshold]")
        print("Example: python Backend/audata/crosspaper_comparator.py BioFactors.pdf BioFactors.pdf 8")
        sys.exit(1)

    paper_a_pdf = sys.argv[1]
    paper_b_pdf = sys.argv[2]
    threshold = int(sys.argv[3]) if len(sys.argv) >= 4 else 8

    result = compare_two_pdfs(
        paper_a_pdf=paper_a_pdf,
        paper_b_pdf=paper_b_pdf,
        threshold=threshold,
    )

    print(f"\nFindings at threshold <= {threshold}: {result['num_findings']}")
    print(f"Paper A figures saved to: {result['paper_a_output_dir']}")
    print(f"Paper B figures saved to: {result['paper_b_output_dir']}")

    for f in result["findings"][:20]:
        print("\nPossible cross-paper figure reuse")
        print("Paper A:", f["paper_a_figure"])
        print("Paper B:", f["paper_b_figure"])
        print("Similarity:", f["similarity_score"])
        print("Hash distance:", f["hash_distance"])
        print("Severity:", f["severity"])