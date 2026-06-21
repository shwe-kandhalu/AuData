"""Image forensics & integrity auditor (AuData).

Checks whether a paper's figures are original, unmanipulated, and not reused from
other papers. Runs copy-move detection, ELA (error-level analysis), and perceptual
hashing to detect image tampering and cross-paper figure reuse.

Supports two workflows:
  1. Paper-dict workflow (ingest integration): accepts Dict[str, Any] from ingest.py,
     extracts figures from stored PDF bytes, integrates with methods_claims and
     reference_integrity checks.
  2. Direct PDF workflow (CLI/debugging): accepts PDF file paths for standalone analysis.

Reviewer-assist — never an automated accusation.
"""

import argparse
import glob
import json
import os
import sys
import tempfile
import re
import subprocess

from dataclasses import dataclass, asdict
from itertools import product
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import cv2
import fitz  # PyMuPDF
import imagehash
import numpy as np
from PIL import Image, ImageChops, ImageEnhance

from . import ingest


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class ImageResult:
    image_path: str
    width: int
    height: int
    ela_score: float
    ela_map_path: Optional[str]
    copy_move_score: float
    copy_move_overlay_path: Optional[str]
    copy_move_match_count: int
    phash: str
    dhash: str
    whash: str
    ai_score: Optional[float]
    flags: List[str]


@dataclass
class DuplicatePair:
    image_a: str
    image_b: str
    phash_distance: int
    dhash_distance: int
    whash_distance: int
    duplicate_score: float


def safe_stem(path: str) -> str:
    return Path(path).stem.replace(" ", "_").replace(".", "_")


# --- Helper to filter out decorative/non-figure PDF images ---
def is_probably_decorative_pdf_image(image_path: Path, bboxes: List[Dict[str, Any]]) -> bool:
    """
    Filter out tiny publisher/UI assets extracted from PDFs, such as logos,
    badges, icons, and browser-style labels like 'Check for updates'.
    These are not scientific figures and should not enter image-forensics comparison.
    """
    try:
        with Image.open(image_path) as img:
            width_px, height_px = img.size
    except Exception:
        return False

    if width_px < 180 or height_px < 80:
        return True

    aspect = width_px / max(height_px, 1)
    if aspect > 8 or aspect < 0.12:
        return True

    if bboxes:
        max_w = max(abs(b.get("x1", 0) - b.get("x0", 0)) for b in bboxes)
        max_h = max(abs(b.get("y1", 0) - b.get("y0", 0)) for b in bboxes)
        if max_w < 120 or max_h < 45 or max_w * max_h < 8000:
            return True

    return False


# --- Utility and Batch-Analysis Functions ---

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def load_cv_image(path: str):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return img


def to_gray(img_bgr):
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)


def make_json_safe(obj):
    """Convert NumPy/OpenCV scalar types into JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def save_json(obj, path: str):
    with open(path, "w") as f:
        json.dump(make_json_safe(obj), f, indent=2)


def normalize_score(x, lo, hi):
    if hi <= lo:
        return 0.0
    x = max(lo, min(hi, x))
    return (x - lo) / (hi - lo)


def compute_ela(image_path: str, out_dir: str, jpeg_quality: int = 90) -> Tuple[float, str]:
    ensure_dir(out_dir)

    orig = Image.open(image_path).convert("RGB")
    fd, tmp_jpg = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)

    try:
        orig.save(tmp_jpg, "JPEG", quality=jpeg_quality)
        recompressed = Image.open(tmp_jpg).convert("RGB")

        diff = ImageChops.difference(orig, recompressed)
        extrema = diff.getextrema()
        max_diff = max([e[1] for e in extrema]) if extrema else 1
        scale = 255.0 / max(max_diff, 1)

        ela_img = ImageEnhance.Brightness(diff).enhance(scale)
        ela_np = np.array(ela_img)
        ela_gray = cv2.cvtColor(ela_np, cv2.COLOR_RGB2GRAY)

        mean_resid = float(np.mean(ela_gray))
        p95_resid = float(np.percentile(ela_gray, 95))
        ela_score = 0.4 * normalize_score(mean_resid, 5, 40) + 0.6 * normalize_score(p95_resid, 20, 180)

        base = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(out_dir, f"{base}_ela.png")
        ela_img.save(out_path)

        return round(float(ela_score), 4), out_path
    finally:
        if os.path.exists(tmp_jpg):
            os.remove(tmp_jpg)


def compute_copy_move(
    image_path: str,
    out_dir: str,
    min_match_count: int = 12,
    spatial_min_dist: float = 25.0,
) -> Tuple[float, str, int]:
    ensure_dir(out_dir)

    img = load_cv_image(image_path)
    gray = to_gray(img)

    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=7)
    keypoints, descriptors = orb.detectAndCompute(gray, None)

    base = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(out_dir, f"{base}_copymove.png")

    if descriptors is None or len(keypoints) < 10:
        cv2.imwrite(out_path, img)
        return 0.0, out_path, 0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn_matches = bf.knnMatch(descriptors, descriptors, k=3)

    candidate_pairs = []
    for group in knn_matches:
        if len(group) < 2:
            continue
        for m in group:
            if m.queryIdx == m.trainIdx:
                continue
            pt1 = np.array(keypoints[m.queryIdx].pt)
            pt2 = np.array(keypoints[m.trainIdx].pt)
            dist = np.linalg.norm(pt1 - pt2)
            if dist >= spatial_min_dist:
                candidate_pairs.append(m)
                break

    if len(candidate_pairs) < min_match_count:
        cv2.imwrite(out_path, img)
        return 0.0, out_path, len(candidate_pairs)

    src_pts = np.float32([keypoints[m.queryIdx].pt for m in candidate_pairs]).reshape(-1, 1, 2)
    dst_pts = np.float32([keypoints[m.trainIdx].pt for m in candidate_pairs]).reshape(-1, 1, 2)

    _, inlier_mask = cv2.estimateAffinePartial2D(
        src_pts,
        dst_pts,
        method=cv2.RANSAC,
        ransacReprojThreshold=5.0,
    )

    overlay = img.copy()
    inlier_count = 0

    if inlier_mask is not None:
        inlier_mask = inlier_mask.ravel().astype(bool)
        inlier_count = int(np.sum(inlier_mask))

        for i, keep in enumerate(inlier_mask):
            if not keep:
                continue
            x1, y1 = map(int, src_pts[i, 0])
            x2, y2 = map(int, dst_pts[i, 0])
            cv2.circle(overlay, (x1, y1), 4, (0, 255, 0), -1)
            cv2.circle(overlay, (x2, y2), 4, (0, 0, 255), -1)
            cv2.line(overlay, (x1, y1), (x2, y2), (255, 0, 0), 1)

    copy_move_score = normalize_score(inlier_count, 8, 80)
    cv2.imwrite(out_path, overlay)

    return round(float(copy_move_score), 4), out_path, inlier_count


def compute_hashes(image_path: str) -> Dict[str, str]:
    img = Image.open(image_path).convert("RGB")
    return {
        "phash": str(imagehash.phash(img)),
        "dhash": str(imagehash.dhash(img)),
        "whash": str(imagehash.whash(img)),
    }


def hash_distance(h1: str, h2: str) -> int:
    return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)


def compare_hash_sets(hash_a: Dict[str, str], hash_b: Dict[str, str]) -> Tuple[int, int, int, float]:
    pd = hash_distance(hash_a["phash"], hash_b["phash"])
    dd = hash_distance(hash_a["dhash"], hash_b["dhash"])
    wd = hash_distance(hash_a["whash"], hash_b["whash"])

    sim = 1.0 - np.mean([
        normalize_score(pd, 0, 20),
        normalize_score(dd, 0, 20),
        normalize_score(wd, 0, 20),
    ])
    return pd, dd, wd, round(float(sim), 4)


def ai_generated_placeholder_score(image_path: str) -> Optional[float]:
    try:
        img = load_cv_image(image_path)
        gray = to_gray(img)

        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        edges = cv2.Canny(gray, 80, 160)
        edge_density = float(np.mean(edges > 0))

        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
        hist = hist / max(float(hist.sum()), 1.0)
        entropy = float(-np.sum(hist * np.log2(hist + 1e-12)))

        smooth_score = 1.0 - normalize_score(lap_var, 20, 800)
        low_edge_score = 1.0 - normalize_score(edge_density, 0.02, 0.20)
        entropy_score = 1.0 - normalize_score(entropy, 3.0, 7.5)

        score = 0.4 * smooth_score + 0.35 * low_edge_score + 0.25 * entropy_score
        return round(float(max(0.0, min(1.0, score))), 4)
    except Exception:
        return None

def compute_image_embedding(image_path: str) -> np.ndarray:
    img = load_cv_image(image_path)
    img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hsv_hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256]).flatten()

    gray = to_gray(img)
    gray_hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).flatten()

    edges = cv2.Canny(gray, 80, 160)
    edge_density = np.array([np.mean(edges > 0)], dtype=np.float32)

    vec = np.concatenate([hsv_hist, gray_hist, edge_density]).astype(np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embedding_similarity(image_a: str, image_b: str) -> float:
    a = compute_image_embedding(image_a)
    b = compute_image_embedding(image_b)
    return round(float(np.dot(a, b)), 4)

def robust_subregion_match(target_image: str, candidate_image: str, output_dir: str) -> Dict[str, Any]:
    ensure_dir(output_dir)

    img_a = load_cv_image(target_image)
    img_b = load_cv_image(candidate_image)

    gray_a = to_gray(img_a)
    gray_b = to_gray(img_b)

    orb = cv2.ORB_create(nfeatures=4000)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)

    if des_a is None or des_b is None or len(kp_a) < 10 or len(kp_b) < 10:
        return {"score": 0.0, "num_inliers": 0, "overlay_path": None}

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(des_a, des_b, k=2)

    good = []
    for pair in matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)

    if len(good) < 4:
        return {"score": 0.0, "num_inliers": 0, "overlay_path": None}

    src_pts = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    _, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    inliers = int(mask.ravel().sum()) if mask is not None else 0

    score = normalize_score(inliers, 10, 80)

    overlay_path = None
    if inliers >= 10:
        base_a = os.path.splitext(os.path.basename(target_image))[0]
        base_b = os.path.splitext(os.path.basename(candidate_image))[0]
        overlay_path = os.path.join(output_dir, f"subregion_{base_a}__{base_b}.png")

        inlier_matches = [m for m, keep in zip(good, mask.ravel().astype(bool)) if keep]
        overlay = cv2.drawMatches(
            img_a,
            kp_a,
            img_b,
            kp_b,
            inlier_matches[:50],
            None,
            flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
        )
        cv2.imwrite(overlay_path, overlay)

    return {
        "score": round(float(score), 4),
        "num_matches": len(good),
        "num_inliers": inliers,
        "overlay_path": overlay_path,
    }

def detect_splice_boundaries(image_path: str, output_dir: str) -> Dict[str, Any]:
    ensure_dir(output_dir)

    img = load_cv_image(image_path)
    gray = to_gray(img)

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    grad_x = cv2.Sobel(blur, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(blur, cv2.CV_64F, 0, 1, ksize=3)

    vertical_profile = np.mean(np.abs(grad_x), axis=0)
    horizontal_profile = np.mean(np.abs(grad_y), axis=1)

    def max_z(profile):
        mu = float(np.mean(profile))
        sd = float(np.std(profile)) + 1e-6
        z = (profile - mu) / sd
        idx = int(np.argmax(z))
        return float(z[idx]), idx

    vz, vx = max_z(vertical_profile)
    hz, hy = max_z(horizontal_profile)

    max_signal = max(vz, hz)
    score = normalize_score(max_signal, 3.0, 8.0)

    overlay = img.copy()
    if vz >= 3.0:
        cv2.line(overlay, (vx, 0), (vx, overlay.shape[0] - 1), (0, 0, 255), 2)
    if hz >= 3.0:
        cv2.line(overlay, (0, hy), (overlay.shape[1] - 1, hy), (0, 0, 255), 2)

    base = os.path.splitext(os.path.basename(image_path))[0]
    overlay_path = os.path.join(output_dir, f"{base}_splice_overlay.png")
    cv2.imwrite(overlay_path, overlay)

    return {
        "score": round(float(score), 4),
        "max_vertical_z": round(float(vz), 4),
        "max_horizontal_z": round(float(hz), 4),
        "overlay_path": overlay_path,
        "severity": "high" if score >= 0.65 else "moderate" if score >= 0.35 else "low",
    }

def analyze_images(image_paths: List[str], out_dir: str, duplicate_threshold: float = 0.80) -> Dict[str, Any]:
    ensure_dir(out_dir)
    ela_dir = os.path.join(out_dir, "ela")
    cm_dir = os.path.join(out_dir, "copy_move")
    ensure_dir(ela_dir)
    ensure_dir(cm_dir)

    results: List[ImageResult] = []
    hashes_by_path = {}

    for path in image_paths:
        img = load_cv_image(path)
        h, w = img.shape[:2]

        ela_score, ela_map_path = compute_ela(path, ela_dir)
        cm_score, cm_overlay_path, cm_count = compute_copy_move(path, cm_dir)
        hset = compute_hashes(path)
        hashes_by_path[path] = hset
        ai_score = ai_generated_placeholder_score(path)

        flags = []
        if ela_score >= 0.55:
            flags.append("ela-anomaly")
        if cm_score >= 0.35 and cm_count >= 12:
            flags.append("copy-move-suspected")
        if ai_score is not None and ai_score >= 0.7:
            flags.append("ai-generated-risk")

        results.append(ImageResult(
            image_path=path,
            width=w,
            height=h,
            ela_score=ela_score,
            ela_map_path=ela_map_path,
            copy_move_score=cm_score,
            copy_move_overlay_path=cm_overlay_path,
            copy_move_match_count=cm_count,
            phash=hset["phash"],
            dhash=hset["dhash"],
            whash=hset["whash"],
            ai_score=ai_score,
            flags=flags,
        ))

    duplicate_pairs: List[DuplicatePair] = []
    for i in range(len(image_paths)):
        for j in range(i + 1, len(image_paths)):
            a, b = image_paths[i], image_paths[j]
            pd, dd, wd, sim = compare_hash_sets(hashes_by_path[a], hashes_by_path[b])
            if sim >= duplicate_threshold:
                duplicate_pairs.append(DuplicatePair(
                    image_a=a,
                    image_b=b,
                    phash_distance=pd,
                    dhash_distance=dd,
                    whash_distance=wd,
                    duplicate_score=sim,
                ))

    report = {
        "images": [asdict(r) for r in results],
        "duplicate_pairs": [asdict(d) for d in duplicate_pairs],
    }

    save_json(report, os.path.join(out_dir, "forensics_report.json"))
    return report


def collect_images_from_dir(input_dir: str, pattern: str = "*.png") -> List[str]:
    image_paths = sorted(glob.glob(os.path.join(input_dir, pattern)))
    if not image_paths:
        exts = ["*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff", "*.bmp", "*.webp"]
        image_paths = []
        for ext in exts:
            image_paths.extend(glob.glob(os.path.join(input_dir, ext)))
        image_paths = sorted(set(image_paths))
    return image_paths


def run_paperclip_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


def paperclip_search_papers(query, source="pmc", limit=5):
    output = run_paperclip_command([
        "paperclip", "search", "-s", source, query
    ])
    ids = re.findall(r"PMC\d+", output)
    return list(dict.fromkeys(ids))[:limit]


def paperclip_list_figures(paper_id):
    output = run_paperclip_command([
        "paperclip", "ls", f"/papers/{paper_id}/figures/"
    ])
    return re.findall(r"[\w\-.]+\.(?:png|jpg|jpeg|tif|tiff|webp)", output, re.I)


def paperclip_download_figures(query, output_root, source="pmc", limit=5):
    paper_ids = paperclip_search_papers(query, source, limit)
    records = []

    for paper_id in paper_ids:
        for fig in paperclip_list_figures(paper_id):
            out_dir = Path(output_root) / "paperclip_candidates" / paper_id
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{paper_id}_{fig}"

            with open(out_path, "wb") as f:
                subprocess.run(
                    ["paperclip", "cat", f"/papers/{paper_id}/figures/{fig}"],
                    stdout=f,
                    stderr=subprocess.PIPE,
                )

            records.append({
                "paper_label": f"paperclip_{paper_id}",
                "source": "paperclip",
                "paperclip_paper_id": paper_id,
                "paperclip_figure_file": fig,
                "bbox": [],
                "image_path": str(out_path),
            })

    return records

def extract_figures_from_pdf(pdf_path: str, output_root: str, paper_label: str) -> List[Dict[str, Any]]:
    """
    Evidence-Engine-style ingest for figures.
    Extracts embedded images from a PDF and stores basic coordinate metadata when available.

    Input:
        pdf_path: target paper PDF
        output_root: output folder
        paper_label: paper_A, candidate_1, etc.

    Output:
        List of figure records with image path, page, xref, bbox list, and source PDF.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(output_root) / paper_label / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    records = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        images = page.get_images(full=True)

        for image_idx, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            ext = base_image["ext"]

            image_name = f"{paper_label}_{safe_stem(str(pdf_path))}_page_{page_idx + 1}_image_{image_idx + 1}.{ext}"
            image_path = out_dir / image_name

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            bboxes = []
            try:
                for rect in page.get_image_rects(xref):
                    bboxes.append({
                        "x0": float(rect.x0),
                        "y0": float(rect.y0),
                        "x1": float(rect.x1),
                        "y1": float(rect.y1),
                    })
            except Exception:
                bboxes = []


            if is_probably_decorative_pdf_image(image_path, bboxes):
                image_path.unlink(missing_ok=True)
                print(f"Skipping decorative/non-figure image: {image_path.name}")
                continue
            
            records.append({
                "paper_label": paper_label,
                "source_pdf": str(pdf_path),
                "page": page_idx + 1,
                "image_index": image_idx + 1,
                "xref": int(xref),
                "bbox": bboxes,
                "image_path": str(image_path),
            })

    return records


def phash_image(image_path: str):
    img = Image.open(image_path).convert("L").resize((256, 256))
    return imagehash.phash(img)


def compare_target_to_candidates(
    target_figures: List[Dict[str, Any]],
    candidate_figures: List[Dict[str, Any]],
    threshold: int = 8,
) -> List[Dict[str, Any]]:
    """
    Near-duplicate search without Redis.
    Compares every target paper figure against every candidate paper figure using perceptual hash.
    """
    target_hashes = {}
    candidate_hashes = {}

    for fig in target_figures:
        try:
            target_hashes[fig["image_path"]] = phash_image(fig["image_path"])
        except Exception as e:
            print(f"Skipping target figure: {fig['image_path']} | {e}")

    for fig in candidate_figures:
        try:
            candidate_hashes[fig["image_path"]] = phash_image(fig["image_path"])
        except Exception as e:
            print(f"Skipping candidate figure: {fig['image_path']} | {e}")

    fig_by_path = {f["image_path"]: f for f in target_figures + candidate_figures}

    findings = []
    closest_pairs = []

    for target_path, candidate_path in product(target_hashes.keys(), candidate_hashes.keys()):
        distance = target_hashes[target_path] - candidate_hashes[candidate_path]
        similarity = round(1 - distance / 64, 3)

        pair = {
            "flag_type": "possible_cross_paper_figure_reuse",
            "target_figure": target_path,
            "candidate_figure": candidate_path,
            "target_metadata": fig_by_path.get(target_path, {}),
            "candidate_metadata": fig_by_path.get(candidate_path, {}),
            "hash_distance": int(distance),
            "similarity_score": similarity,
            "severity": "high" if distance <= 4 else "moderate",
        }

        closest_pairs.append(pair)

        if distance <= threshold:
            findings.append(pair)

    findings.sort(key=lambda x: x["hash_distance"])
    closest_pairs.sort(key=lambda x: x["hash_distance"])

    return findings, closest_pairs[:10]


def ela_analysis(image_path: str, output_dir: str, quality: int = 90) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    original = Image.open(image_path).convert("RGB")
    temp_path = output_dir / f"{Path(image_path).stem}_temp_compressed.jpg"
    ela_path = output_dir / f"{Path(image_path).stem}_ela.png"

    original.save(temp_path, "JPEG", quality=quality)
    compressed = Image.open(temp_path).convert("RGB")

    diff = ImageChops.difference(original, compressed)
    extrema = diff.getextrema()
    max_diff = max(ex[1] for ex in extrema)

    scale = 255.0 / max_diff if max_diff != 0 else 1
    ela_img = ImageEnhance.Brightness(diff).enhance(scale)
    ela_img.save(ela_path)

    temp_path.unlink(missing_ok=True)
    return str(ela_path)


def copy_move_detection(image_path: str, output_dir: str, min_matches: int = 12) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(image_path))
    if img is None:
        return {
            "flag_type": "copy_move_detection",
            "status": "error",
            "image_path": image_path,
            "message": "Could not read image.",
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=3000)
    keypoints, descriptors = orb.detectAndCompute(gray, None)

    if descriptors is None or keypoints is None or len(keypoints) < 20:
        return {
            "flag_type": "copy_move_detection",
            "status": "no_signal",
            "image_path": image_path,
            "num_keypoints": len(keypoints) if keypoints else 0,
            "num_suspicious_matches": 0,
            "severity": "none",
        }

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(descriptors, descriptors)

    suspicious = []
    for m in matches:
        if m.queryIdx == m.trainIdx:
            continue

        pt1 = np.array(keypoints[m.queryIdx].pt)
        pt2 = np.array(keypoints[m.trainIdx].pt)
        spatial_distance = np.linalg.norm(pt1 - pt2)

        if spatial_distance > 40 and m.distance < 35:
            suspicious.append(m)

    suspicious = sorted(suspicious, key=lambda x: x.distance)
    overlay_path = output_dir / f"{Path(image_path).stem}_copy_move_overlay.png"

    matched_img = cv2.drawMatches(
        img,
        keypoints,
        img,
        keypoints,
        suspicious[:50],
        None,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    cv2.imwrite(str(overlay_path), matched_img)

    severity = "high" if len(suspicious) >= min_matches else "low"

    return {
        "flag_type": "possible_copy_move_manipulation",
        "status": "completed",
        "image_path": image_path,
        "num_keypoints": len(keypoints),
        "num_suspicious_matches": len(suspicious),
        "severity": severity,
        "overlay_path": str(overlay_path),
        "review_note": (
            "Repeated local features were detected in spatially separated regions. "
            "This is a screening signal for possible copy-move manipulation and requires manual review."
        ),
    }


def prepare_paper_figures(paper: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract figures from a paper dict (ingest workflow integration).

    Similar to prepare_paper_references() in reference_integrity.py, this
    prepares figure records for a paper using its stored PDF.
    Returns a list of figure dicts with image paths and metadata.
    """
    from . import storage

    if not paper.get("has_pdf"):
        return []

    pdf_bytes = None
    try:
        pdf_bytes = storage.get_pdf(paper.get("id", ""))
    except Exception:
        return []

    if not pdf_bytes:
        return []

    import tempfile
    fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        with open(temp_pdf_path, "wb") as f:
            f.write(pdf_bytes)
        paper_label = f"paper_{paper.get('id', 'unknown')[:8]}"
        figures = extract_figures_from_pdf(
            temp_pdf_path,
            output_root=str(Path.home() / ".audata" / "figures"),
            paper_label=paper_label,
        )
        return figures
    except Exception:
        return []
    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)


_VLM_PROMPT = (
    "You are a scientific-image-integrity reviewer. Examine this figure from a research paper. "
    "Look for signs of digital manipulation (splicing, cloning, erased regions, inconsistent "
    "backgrounds in blots/micrographs) or AI generation (implausible textures, fabricated detail). "
    "Most figures are clean charts or normal photos. Respond ONLY with JSON: "
    '{"verdict": "clean" | "manipulation_suspected" | "ai_generated", '
    '"confidence": 0.0-1.0, "reason": "one sentence"}.'
)


def vlm_assess(image_path: str, model_name: str = "", timeout: float = 60.0) -> Optional[Dict[str, Any]]:
    """Best-effort multimodal judgement (Qwen-VL / MedGemma via Ollama) of whether a
    figure looks manipulated or AI-generated. Returns None if no vision model responds,
    so it never breaks the deterministic checks."""
    name = model_name or os.getenv("MODEL_VISION") or "qwen2.5vl:7b"
    try:
        import base64
        import requests
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        resp = requests.post(
            f"{base}/api/chat",
            json={"model": name, "stream": False, "options": {"temperature": 0},
                  "messages": [{"role": "user", "content": _VLM_PROMPT, "images": [b64]}]},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        content = (resp.json().get("message") or {}).get("content", "")
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not isinstance(data, dict) or "verdict" not in data:
            return None
        v = str(data.get("verdict", "clean")).strip().lower()
        if v not in ("clean", "manipulation_suspected", "ai_generated"):
            v = "clean"
        try:
            conf = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        return {"verdict": v, "confidence": round(conf, 2), "reason": str(data.get("reason", "")).strip()}
    except Exception as e:
        print(f"[imgforensics.vlm] {e}")
        return None


def run_single_figure_forensics(target_figures: List[Dict[str, Any]], output_root: str,
                                use_vlm: bool = False) -> List[Dict[str, Any]]:
    """
    Runs OpenCV copy-move detection and ELA on every figure extracted from the target paper.
    When use_vlm is set, also runs a vision-model manipulation / AI-generation assessment.
    """
    forensic_dir = Path(output_root) / "paper_A" / "forensics"
    forensic_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for fig in target_figures:
        image_path = fig["image_path"]
        try:
            ela_path = ela_analysis(image_path, forensic_dir)
            copy_move = copy_move_detection(image_path, forensic_dir)
            splice_result = detect_splice_boundaries(image_path, forensic_dir)
            ai_score = ai_generated_placeholder_score(image_path)
            vlm_result = vlm_assess(image_path) if use_vlm else None

            results.append({
                "image_path": image_path,
                "metadata": fig,
                "ela_output_path": ela_path,
                "copy_move_result": copy_move,
                "splice_result": splice_result,
                "ai_generated_score": ai_score,
                "ai_detector_note": "Heuristic placeholder only; replace with a validated detector before using as evidence.",
                "vlm_result": vlm_result,
            })
        except Exception as e:
            results.append({
                "image_path": image_path,
                "metadata": fig,
                "status": "error",
                "error": str(e),
            })

    return results


def summarize_forensics_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate forensics check results by severity and issue type."""
    by_severity: Dict[str, int] = {}
    by_flag: Dict[str, int] = {}

    for r in results:
        if r.get("status") == "error":
            by_flag["error"] = by_flag.get("error", 0) + 1
            continue

        copy_move = r.get("copy_move_result", {})
        if copy_move.get("severity"):
            sev = copy_move["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if sev in ("high", "moderate"):
                by_flag["copy_move_detected"] = by_flag.get("copy_move_detected", 0) + 1

        splice = r.get("splice_result", {})
        if splice.get("severity"):
            sev = splice["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if sev in ("high", "moderate"):
                by_flag["splice_detected"] = by_flag.get("splice_detected", 0) + 1

        ai_score = r.get("ai_generated_score")
        if ai_score is not None and ai_score >= 0.7:
            by_flag["ai_generated_risk"] = by_flag.get("ai_generated_risk", 0) + 1

        vlm = r.get("vlm_result") or {}
        if vlm.get("verdict") in ("manipulation_suspected", "ai_generated") and (vlm.get("confidence") or 0) >= 0.5:
            by_flag[f"vlm_{vlm['verdict']}"] = by_flag.get(f"vlm_{vlm['verdict']}", 0) + 1

    def _vlm_flagged(r):
        v = r.get("vlm_result") or {}
        return v.get("verdict") in ("manipulation_suspected", "ai_generated") and (v.get("confidence") or 0) >= 0.5

    return {
        "total_images": len(results),
        "flagged": sum(1 for r in results if r.get("status") == "error" or _vlm_flagged(r) or
                       any(r.get(k, {}).get("severity") in ("high", "moderate")
                           for k in ("copy_move_result", "splice_result"))),
        "by_severity": by_severity,
        "by_flag": by_flag,
    }


def run_image_integrity_agent_from_papers(
    target_paper: Dict[str, Any],
    candidate_papers: List[Dict[str, Any]],
    output_root: str = "image_integrity_output",
    similarity_threshold: int = 8,
    use_vlm: bool = False,
) -> Dict[str, Any]:
    """
    Full Image Auditor MVP integrated with ingest workflow.

    Accepts paper dicts (from ingest.py) instead of PDF file paths.
    Uses has_pdf flag and pdf_id to locate extracted PDF for figure extraction.

    1. Extract figures from target paper's PDF.
    2. Extract figures from candidate papers' PDFs.
    3. Compare figures for near-duplicate reuse.
    4. Run image-forensics checks on target paper figures.
    """
    from . import storage

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    paper_label = "paper_A"
    print(f"Target paper: {target_paper.get('title', 'Unknown')}")

    pdf_bytes = None
    if target_paper.get("has_pdf"):
        try:
            pdf_bytes = storage.get_pdf(target_paper.get("id", ""))
        except Exception as e:
            print(f"Warning: Could not load PDF for target paper: {e}")

    if not pdf_bytes:
        print("Error: Target paper has no PDF available")
        return {
            "agent": "image_integrity_agent_from_papers",
            "status": "error",
            "message": "Target paper PDF not available",
        }

    fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(temp_pdf_path, "wb") as f:
            f.write(pdf_bytes)
        target_figures = extract_figures_from_pdf(temp_pdf_path, output_root, paper_label=paper_label)
    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    print(f"Target figures extracted: {len(target_figures)}")

    all_candidate_figures = []
    for idx, candidate_paper in enumerate(candidate_papers, start=1):
        label = f"candidate_{idx}"
        print(f"Candidate paper {idx}: {candidate_paper.get('title', 'Unknown')}")

        pdf_bytes = None
        if candidate_paper.get("has_pdf"):
            try:
                pdf_bytes = storage.get_pdf(candidate_paper.get("id", ""))
            except Exception as e:
                print(f"Warning: Could not load PDF for candidate {idx}: {e}")
                continue

        if not pdf_bytes:
            print(f"Skipping candidate {idx}: PDF not available")
            continue

        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            with open(temp_pdf_path, "wb") as f:
                f.write(pdf_bytes)
            candidate_figures = extract_figures_from_pdf(temp_pdf_path, output_root, paper_label=label)
        finally:
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

        print(f"Candidate {idx} figures extracted: {len(candidate_figures)}")
        all_candidate_figures.extend(candidate_figures)

    print("Running cross-paper near-duplicate search...")
    cross_paper_findings, closest_pairs = compare_target_to_candidates(
        target_figures=target_figures,
        candidate_figures=all_candidate_figures,
        threshold=similarity_threshold,
    )

    print("Running Paper A image-forensics checks...")
    figure_forensics = run_single_figure_forensics(target_figures, output_root, use_vlm=use_vlm)

    # Redis vector search (embedding-based cross-paper reuse). Gated on a real
    # Redis (REDIS_URL), the embedding model, and AUDATA_IMAGE_VECTORS=1.
    vector_findings = []
    if os.getenv("AUDATA_IMAGE_VECTORS", "").lower() in ("1", "true", "yes") and os.getenv("REDIS_URL"):
        try:
            from . import image_vector_store as ivs
            ivs.create_index(overwrite=False)
            panels = [{"panel_path": f["image_path"], "page": f.get("page", 0),
                       "source_figure": str(f.get("xref", "")), "panel_id": f"fig_{i + 1}"}
                      for i, f in enumerate(target_figures) if f.get("image_path")]
            pid = target_paper.get("id", "")
            matches = ivs.search_many_panels(pid, panels, top_k=5)
            vector_findings = [m for m in matches if m.get("paper_id") and m.get("paper_id") != pid]
            ivs.store_many_panels(pid, panels)   # index this paper for future cross-paper checks
            print(f"[imgforensics] Redis vector search: {len(vector_findings)} cross-paper matches.")
        except Exception as e:
            print(f"[imgforensics] vector search skipped: {e}")

    report = {
        "agent": "image_integrity_agent_from_papers",
        "target_paper_id": target_paper.get("id"),
        "target_paper_title": target_paper.get("title"),
        "candidate_paper_ids": [p.get("id") for p in candidate_papers],
        "num_target_figures": len(target_figures),
        "num_candidate_figures": len(all_candidate_figures),
        "num_cross_paper_findings": len(cross_paper_findings),
        "target_figures": target_figures,
        "candidate_figures": all_candidate_figures,
        "cross_paper_findings": cross_paper_findings,
        "closest_cross_paper_pairs": closest_pairs,
        "figure_forensics": figure_forensics,
        "vector_findings": vector_findings,
    }

    report_path = output_root / "image_integrity_report.json"
    save_json(report, str(report_path))

    report["report_path"] = str(report_path)
    return report


def run_image_integrity_agent(
    target_pdf: str,
    candidate_pdfs: List[str],
    output_root: str = "image_integrity_output",
    similarity_threshold: int = 8,
) -> Dict[str, Any]:
    """
    Full Image Auditor MVP.

    1. Ingest target Paper A and extract figures with coordinate metadata.
    2. Ingest multiple candidate papers and extract figures.
    3. Compare Paper A figures against all candidate figures for near-duplicate reuse.
    4. Run image-forensics checks on Paper A figures: ELA + copy-move detection.

    This replaces Redis with direct candidate-paper comparison for the hackathon MVP.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"Target paper: {target_pdf}")
    target_figures = extract_figures_from_pdf(target_pdf, output_root, paper_label="paper_A")
    print(f"Target figures extracted: {len(target_figures)}")

    all_candidate_figures = []
    for idx, candidate_pdf in enumerate(candidate_pdfs, start=1):
        label = f"candidate_{idx}"
        print(f"Candidate paper {idx}: {candidate_pdf}")
        candidate_figures = extract_figures_from_pdf(candidate_pdf, output_root, paper_label=label)
        print(f"Candidate {idx} figures extracted: {len(candidate_figures)}")
        all_candidate_figures.extend(candidate_figures)

    print("Running cross-paper near-duplicate search...")
    cross_paper_findings, closest_pairs = compare_target_to_candidates(
        target_figures=target_figures,
        candidate_figures=all_candidate_figures,
        threshold=similarity_threshold,
    )

    print("Running Paper A image-forensics checks...")
    figure_forensics = run_single_figure_forensics(target_figures, output_root)

    report = {
        "agent": "image_integrity_agent",
        "target_pdf": target_pdf,
        "candidate_pdfs": candidate_pdfs,
        "num_target_figures": len(target_figures),
        "num_candidate_figures": len(all_candidate_figures),
        "num_cross_paper_findings": len(cross_paper_findings),
        "target_figures": target_figures,
        "candidate_figures": all_candidate_figures,
        "cross_paper_findings": cross_paper_findings,
        "closest_cross_paper_pairs": closest_pairs,
        "figure_forensics": figure_forensics,
    }

    report_path = output_root / "image_integrity_report.json"
    save_json(report, str(report_path))

    report["report_path"] = str(report_path)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", nargs="*", help="Target paper followed by candidate paper PDFs")
    parser.add_argument("--threshold", type=int, default=8, help="pHash distance threshold for cross-paper reuse")
    parser.add_argument("--input_dir", help="Directory containing extracted figure or panel images for standalone image forensics")
    parser.add_argument("--output_dir", default="image_forensics_output", help="Directory for artifacts and report")
    parser.add_argument("--glob", default="*", help="Image glob pattern for --input_dir mode")
    parser.add_argument("--paperclip_query")
    parser.add_argument("--paperclip_source", default="pmc")
    parser.add_argument("--paperclip_limit", type=int, default=5)
    args = parser.parse_args()

    if args.input_dir:
        image_paths = collect_images_from_dir(args.input_dir, args.glob)
        if not image_paths:
            print(f"No images found in {args.input_dir}")
            sys.exit(1)

        report = analyze_images(image_paths, args.output_dir)
        print(json.dumps({
            "mode": "standalone_image_forensics",
            "n_images": len(report["images"]),
            "n_duplicate_pairs": len(report["duplicate_pairs"]),
            "report_path": str(Path(args.output_dir) / "forensics_report.json"),
        }, indent=2))
        sys.exit(0)

    if args.paperclip_query:
        if len(args.pdfs) < 1:
            print("Usage for Paperclip mode:")
            print("  python Backend/audata/imageforensicsagents.py target_paper.pdf --paperclip_query \"icariin benign prostatic hyperplasia miR7\" --paperclip_limit 5")
            sys.exit(1)

        target_pdf = args.pdfs[0]
        output_root = Path(args.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)

        print(f"Target paper: {target_pdf}")
        target_figures = extract_figures_from_pdf(target_pdf, output_root, paper_label="paper_A")
        print(f"Target figures extracted: {len(target_figures)}")

        print(f"Searching Paperclip with query: {args.paperclip_query}")
        candidate_figures = paperclip_download_figures(
            query=args.paperclip_query,
            output_root=args.output_dir,
            source=args.paperclip_source,
            limit=args.paperclip_limit,
        )
        print(f"Paperclip candidate figures downloaded: {len(candidate_figures)}")

        print("Running Paperclip cross-paper near-duplicate search...")
        cross_paper_findings, closest_pairs = compare_target_to_candidates(
            target_figures=target_figures,
            candidate_figures=candidate_figures,
            threshold=args.threshold,
        )

        print("Running Paper A image-forensics checks...")
        figure_forensics = run_single_figure_forensics(target_figures, output_root)

        report = {
            "agent": "image_integrity_agent_paperclip",
            "target_pdf": target_pdf,
            "paperclip_query": args.paperclip_query,
            "paperclip_source": args.paperclip_source,
            "paperclip_limit": args.paperclip_limit,
            "num_target_figures": len(target_figures),
            "num_candidate_figures": len(candidate_figures),
            "num_cross_paper_findings": len(cross_paper_findings),
            "target_figures": target_figures,
            "candidate_figures": candidate_figures,
            "cross_paper_findings": cross_paper_findings,
            "closest_cross_paper_pairs": closest_pairs,
            "figure_forensics": figure_forensics,
        }

        report_path = output_root / "image_integrity_paperclip_report.json"
        save_json(report, str(report_path))

        print("\nPaperclip Image Integrity Agent Complete")
        print(f"Target figures: {len(target_figures)}")
        print(f"Paperclip candidate figures: {len(candidate_figures)}")
        print(f"Cross-paper findings: {len(cross_paper_findings)}")
        print(f"Report saved to: {report_path}")

        print("\nClosest Paperclip cross-paper pairs:")
        for pair in closest_pairs[:5]:
            print(
                f"distance={pair['hash_distance']} similarity={pair['similarity_score']} | "
                f"target={Path(pair['target_figure']).name} | candidate={Path(pair['candidate_figure']).name}"
            )

        for finding in cross_paper_findings[:10]:
            print("\nPossible cross-paper figure reuse")
            print("Target:", finding["target_figure"])
            print("Candidate:", finding["candidate_figure"])
            print("Similarity:", finding["similarity_score"])
            print("Hash distance:", finding["hash_distance"])
            print("Severity:", finding["severity"])
        sys.exit(0)

    if len(args.pdfs) < 2:
        print("Usage for full agent:")
        print("  python Backend/audata/imageforensicsagents.py target_paper.pdf candidate1.pdf [candidate2.pdf ...] --threshold 8")
        print("Usage for extracted-image forensics:")
        print("  python Backend/audata/imageforensicsagents.py --input_dir image_integrity_output/paper_A/figures --output_dir forensics_output")
        sys.exit(1)

    target_pdf = args.pdfs[0]
    candidate_pdfs = args.pdfs[1:]

    result = run_image_integrity_agent(
        target_pdf=target_pdf,
        candidate_pdfs=candidate_pdfs,
        output_root=args.output_dir,
        similarity_threshold=args.threshold,
    )

    print("\nImage Integrity Agent Complete")
    print(f"Target figures: {result['num_target_figures']}")
    print(f"Candidate figures: {result['num_candidate_figures']}")
    print(f"Cross-paper findings: {result['num_cross_paper_findings']}")
    print(f"Report saved to: {result['report_path']}")

    print("\nClosest cross-paper pairs:")
    for pair in result["closest_cross_paper_pairs"][:5]:
        print(
            f"distance={pair['hash_distance']} similarity={pair['similarity_score']} | "
            f"target={Path(pair['target_figure']).name} | candidate={Path(pair['candidate_figure']).name}"
        )

    for finding in result["cross_paper_findings"][:10]:
        print("\nPossible cross-paper figure reuse")
        print("Target:", finding["target_figure"])
        print("Candidate:", finding["candidate_figure"])
        print("Similarity:", finding["similarity_score"])
        print("Hash distance:", finding["hash_distance"])
        print("Severity:", finding["severity"])

        