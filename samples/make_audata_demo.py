"""Generate a small demo paper PDF with planted integrity errors so every AuData
detector fires: a wrong p-value (statcheck), a GRIM-impossible mean, and
duplicated photographic figures (image forensics).

    python samples/make_audata_demo.py   ->  samples/audata_demo.pdf
"""

import io
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image


def blob(h, w, seed):
    """A continuous-tone, structured texture (passes the photographic gate)."""
    r = np.random.default_rng(seed)
    a = r.integers(40, 210, (h, w), dtype=np.uint8)
    for _ in range(70):
        cy, cx = int(r.integers(12, h - 12)), int(r.integers(12, w - 12))
        a[cy - 7:cy + 7, cx - 7:cx + 7] = int(r.integers(0, 255))
    return a


def png(arr):
    b = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(b, "PNG")
    return b.getvalue()


# --- figures with planted duplication ---
f1 = blob(600, 600, 5)
patch = f1[40:180, 40:180].copy()
f1[380:520, 380:520] = patch          # internal clone  -> region_duplication
# near-identical copy (light noise so it is a distinct image, not deduped by the PDF)
_r2 = np.random.default_rng(99)
f2 = f1.astype(np.int16)
_mask = _r2.random(f2.shape) < 0.01
f2[_mask] = np.clip(f2[_mask] + _r2.integers(-30, 30, int(_mask.sum())), 0, 255)
f2 = f2.astype(np.uint8)                # whole-figure near-duplicate -> duplicate_figure
f3 = blob(600, 600, 9)
f3[300:440, 300:440] = patch           # shared panel with f1 -> panel_reuse

TEXT_P1 = (
    "A Demonstration Paper for Research-Integrity Auditing\n\n"
    "Abstract. This synthetic paper contains deliberately planted statistical and "
    "image errors so that an automated integrity auditor can be evaluated end to end. "
    "It is not a real study.\n\n"
    "Methods and Results. Participants were randomly assigned to a treatment or control "
    "group. The treatment improved performance, and the difference was statistically "
    "significant, t(19) = 2.1, p < .01.\n\n"
    "Participants also rated their satisfaction on a 7-point Likert item with integer "
    "responses from 1 to 7. The treatment group (n = 28) reported a mean satisfaction of "
    "5.19 (SD = 1.30), while the control group (n = 28) reported a mean of 4.00 (SD = 1.10).\n\n"
    "Of the 200 enrolled participants, 38% (62 of 200) achieved remission. The cohort "
    "comprised 120 women and 75 men.\n\n"
    "Figure 1 and Figure 2 show representative microscopy fields; Figure 3 shows an "
    "additional field from a separate sample.\n\n"
    "Meta-analysis. We pooled four studies in a random-effects meta-analysis of treatment "
    "versus control. The pooled odds ratio was 3.20 (95% CI 2.40 to 4.27). Included studies: "
    "Almeida 2018 OR 2.10 (1.40-3.15); Becker 2019 OR 1.50 (1.05-2.14); Cho 2020 OR 2.40 "
    "(1.50-3.84); Diaz 2021 OR 1.20 (0.80-1.80)."
)


def main():
    out = Path(__file__).resolve().parent / "audata_demo.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_textbox(fitz.Rect(54, 54, 558, 760), TEXT_P1, fontsize=12, fontname="helv")

    p2 = doc.new_page()
    p2.insert_textbox(fitz.Rect(54, 40, 558, 60), "Figure 1 (left) and Figure 2 (right)", fontsize=11)
    p2.insert_image(fitz.Rect(54, 70, 300, 316), stream=png(f1))
    p2.insert_image(fitz.Rect(312, 70, 558, 316), stream=png(f2))

    p3 = doc.new_page()
    p3.insert_textbox(fitz.Rect(54, 40, 558, 60), "Figure 3", fontsize=11)
    p3.insert_image(fitz.Rect(54, 70, 300, 316), stream=png(f3))

    doc.save(str(out))
    doc.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
