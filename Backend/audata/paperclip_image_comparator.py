import re
import subprocess
from pathlib import Path
from itertools import product

from PIL import Image
import imagehash


PAPERCLIP_FIG_DIR = Path("paperclip_figures")
PAPERCLIP_FIG_DIR.mkdir(exist_ok=True)


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


def search_paperclip_papers(query, source="pmc", limit=5):
    output = run_cmd([
        "paperclip", "search",
        "-s", source,
        query
    ])

    pmc_ids = re.findall(r"PMC\d+", output)
    return list(dict.fromkeys(pmc_ids))[:limit]


def list_paperclip_figures(paper_id):
    output = run_cmd([
        "paperclip", "ls",
        f"/papers/{paper_id}/figures/"
    ])

    files = []
    for line in output.splitlines():
        match = re.search(r"([\w\-\.]+\.(?:png|jpg|jpeg|tif|tiff))", line, re.I)
        if match:
            files.append(match.group(1))

    return files


def download_paperclip_figure(paper_id, figure_file):
    output_path = PAPERCLIP_FIG_DIR / f"{paper_id}_{figure_file}"

    with open(output_path, "wb") as f:
        subprocess.run(
            ["paperclip", "cat", f"/papers/{paper_id}/figures/{figure_file}"],
            stdout=f,
            check=True
        )

    return str(output_path)


def fetch_reference_figures(query, source="pmc", paper_limit=5):
    paper_ids = search_paperclip_papers(query, source=source, limit=paper_limit)

    downloaded = []

    for paper_id in paper_ids:
        try:
            figures = list_paperclip_figures(paper_id)

            for fig in figures:
                try:
                    path = download_paperclip_figure(paper_id, fig)
                    downloaded.append({
                        "paper_id": paper_id,
                        "figure_file": fig,
                        "path": path
                    })
                except Exception:
                    pass

        except Exception:
            pass

    return downloaded


def phash_image(path):
    img = Image.open(path).convert("L").resize((256, 256))
    return imagehash.phash(img)


def compare_against_paperclip(query_panel_dir, paperclip_query, threshold=8):
    query_paths = [
        p for p in Path(query_panel_dir).glob("*")
        if p.suffix.lower() in [".png", ".jpg", ".jpeg", ".tif", ".tiff"]
    ]

    reference_figures = fetch_reference_figures(paperclip_query)

    query_hashes = {str(p): phash_image(p) for p in query_paths}
    ref_hashes = {
        ref["path"]: phash_image(ref["path"])
        for ref in reference_figures
    }

    findings = []

    for query_path, ref_path in product(query_hashes.keys(), ref_hashes.keys()):
        distance = query_hashes[query_path] - ref_hashes[ref_path]
        similarity = round(1 - distance / 64, 3)

        if distance <= threshold:
            ref_meta = next(r for r in reference_figures if r["path"] == ref_path)

            findings.append({
                "flag_type": "possible_cross_paper_figure_reuse",
                "query_panel": query_path,
                "reference_figure": ref_path,
                "reference_paper_id": ref_meta["paper_id"],
                "hash_distance": int(distance),
                "similarity_score": similarity,
                "severity": "high" if distance <= 4 else "moderate"
            })

    findings.sort(key=lambda x: x["hash_distance"])
    return findings


if __name__ == "__main__":
    findings = compare_against_paperclip(
        query_panel_dir="image_auditor_output/panels",
        paperclip_query="PI3K AKT Raf ERK oxidative stress western blot",
        threshold=8
    )

    print(f"Findings: {len(findings)}")

    for f in findings[:10]:
        print("\nPossible cross-paper reuse")
        print(f"Query panel: {f['query_panel']}")
        print(f"Reference: {f['reference_figure']}")
        print(f"Reference paper: {f['reference_paper_id']}")
        print(f"Similarity: {f['similarity_score']}")
        print(f"Hash distance: {f['hash_distance']}")