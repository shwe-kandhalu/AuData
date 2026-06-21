# run_demo.py

from Backend.browserbase_input import download_pdf_with_browserbase
from Backend.image_auditor_agent import run_image_auditor

url = " https://iubmb.onlinelibrary.wiley.com/doi/epdf/10.1002/biof.1591"

pdf_path = download_pdf_with_browserbase(url)
report = run_image_auditor(pdf_path)

print(report)