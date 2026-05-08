import os
import re
import json
import zipfile
import requests
import pandas as pd
import xml.etree.ElementTree as ET

from docx import Document
from PyPDF2 import PdfReader
from dotenv import load_dotenv

# =====================================================
# SETTINGS
# =====================================================

TEST_MODE = False       # True = skip Claude calls entirely
BATCH_SIZE = 5          # Number of files to send per Claude API call

# Load .env from the same folder as this script, regardless of where terminal is
script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, ".env")
load_dotenv(dotenv_path=dotenv_path)
API_KEY = os.getenv("CLAUDE_API_KEY")

# Debug: show exactly where it looked and what it found
print(f"Looking for .env at: {dotenv_path}")
print(f"File exists: {os.path.exists(dotenv_path)}")
print(f"API key loaded: {'YES' if API_KEY else 'NO'}")

if not API_KEY:
    raise ValueError(
        "Claude API key not found. "
        "Create a .env file in the same folder as this script with:\n"
        "CLAUDE_API_KEY=sk-ant-..."
    )
print("API key loaded successfully.")

# =====================================================
# CORRECT MODEL STRING
# =====================================================
# Do NOT use "latest" aliases — they are not supported in direct API calls.
# Always use the full dated model string.

MODEL = "claude-haiku-4-5-20251001"   # Cheapest + fastest — ideal for classification

# =====================================================
# READ PDF
# =====================================================

def read_pdf(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        print(f"  PDF read error: {file_path} | {e}")
    return text.strip()


# =====================================================
# READ DOCX
# =====================================================

def read_docx(file_path):
    text = ""
    try:
        doc = Document(file_path)

        for para in doc.paragraphs:
            if para.text.strip():
                text += para.text + "\n"

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        text += cell.text + "\n"

        for section in doc.sections:
            for para in section.header.paragraphs:
                if para.text.strip():
                    text += para.text + "\n"
            for para in section.footer.paragraphs:
                if para.text.strip():
                    text += para.text + "\n"

        # XML fallback for text boxes / template text
        with zipfile.ZipFile(file_path) as z:
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            for node in tree.iter():
                if node.text and node.text.strip():
                    text += node.text.strip() + "\n"

    except Exception as e:
        print(f"  DOCX read error: {file_path} | {e}")
    return text.strip()


# =====================================================
# SANITISE TEXT
# =====================================================

def sanitise_text(text):
    text = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', '[EMAIL_REMOVED]', text)
    text = re.sub(r'(\+?\d[\d\s\-]{7,}\d)', '[PHONE_REMOVED]', text)
    text = re.sub(r'https?://(www\.)?linkedin\.com/[^\s]+', '[LINKEDIN_REMOVED]', text)
    text = re.sub(r'https?://\S+|www\.\S+', '[URL_REMOVED]', text)
    text = re.sub(r'\b\d{1,5}\s+\w+(\s\w+){1,4}', '[ADDRESS_REMOVED]', text)

    names_to_remove = ["Pradyut Rawul"]
    for name in names_to_remove:
        text = text.replace(name, '[NAME_REMOVED]')

    return text.strip()


# =====================================================
# SAVE SANITISED PREVIEW
# =====================================================

def save_sanitised_preview(company, filename, text):
    output_dir = "sanitised_output"
    os.makedirs(output_dir, exist_ok=True)
    safe_company = re.sub(r'[^\w\-]', '_', company)
    safe_file = re.sub(r'[^\w\-\.]', '_', filename)
    output_file = os.path.join(output_dir, f"{safe_company}_{safe_file}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  Preview saved: {output_file}")


# =====================================================
# BATCHED CLAUDE KEYWORD EXTRACTION
#
# Sends multiple documents in a single API call.
# Each document is numbered so Claude can return
# separate keyword sets in one response.
#
# Input:  list of (company, filename, sanitised_text) tuples
# Output: list of (company, filename, keywords_dict) tuples
# =====================================================

def extract_keywords_batch(items):
    """
    items: list of (company, filename, sanitised_text)
    Returns: list of (company, filename, keywords_dict)
    """

    # Build a numbered document block for each item
    doc_blocks = []
    for i, (company, filename, text) in enumerate(items, start=1):
        # Truncate each doc to stay within context limits
        truncated = text[:6000]
        doc_blocks.append(
            f"### DOCUMENT {i}: {company} / {filename}\n{truncated}"
        )

    combined = "\n\n".join(doc_blocks)

    prompt = f"""You will analyse {len(items)} resume or cover letter document(s) below.

For EACH document, extract explicit keywords and classify them.

Return ONLY a JSON array — one object per document, in the same order as the documents.
Each object must have this exact structure:
{{
  "technical_skills": [],
  "tools": [],
  "soft_skills": [],
  "methodologies": [],
  "domain_terms": []
}}

Rules:
- Return ONLY the JSON array. No explanation, no markdown, no backticks.
- Base extraction strictly on the text provided — no assumptions.
- Remove duplicates within each category.
- Use concise phrases only.

DOCUMENTS:
{combined}
"""

    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=90
    )

    if response.status_code != 200:
        print(f"  API error {response.status_code}: {response.text}")
        response.raise_for_status()

    raw_output = response.json()["content"][0]["text"].strip()

    # Strip markdown fences if Claude adds them despite instructions
    raw_output = re.sub(r"^```(?:json)?", "", raw_output).strip()
    raw_output = re.sub(r"```$", "", raw_output).strip()

    keyword_list = json.loads(raw_output)

    # Pair results back to their source files
    results = []
    for i, (company, filename, _) in enumerate(items):
        kw = keyword_list[i] if i < len(keyword_list) else {}
        results.append((company, filename, kw))

    return results


# =====================================================
# FILE SELECTION LOGIC
# Resume  → prefer DOCX
# Cover Letter → prefer PDF
# =====================================================

def select_files(files):
    grouped = {}
    for filename in files:
        base, ext = os.path.splitext(filename)
        ext = ext.lower()
        if ext not in [".pdf", ".docx"]:
            continue
        grouped.setdefault(base.lower(), []).append(filename)

    selected = []
    for base, versions in grouped.items():
        pdf_files  = [f for f in versions if f.lower().endswith(".pdf")]
        docx_files = [f for f in versions if f.lower().endswith(".docx")]

        if "cover" in base:
            # Cover letter: prefer PDF (rendered body text)
            selected.append(pdf_files[0] if pdf_files else docx_files[0] if docx_files else None)
        else:
            # Resume: prefer DOCX (clean extraction via python-docx)
            selected.append(docx_files[0] if docx_files else pdf_files[0] if pdf_files else None)

    return [f for f in selected if f]


# =====================================================
# PROCESS FOLDERS
# =====================================================

def process_folder(root_folder):
    rows = []

    # Step 1: Collect all files to process
    pending = []   # list of (company, filename, file_path)

    for current_folder, _, files in os.walk(root_folder):
        company = os.path.basename(current_folder)
        selected_files = select_files(files)

        for filename in selected_files:
            file_path = os.path.join(current_folder, filename)
            pending.append((company, filename, file_path))

    print(f"\nTotal files selected: {len(pending)}")

    # Step 2: Extract + sanitise text from all files
    sanitised_items = []   # list of (company, filename, sanitised_text)

    for company, filename, file_path in pending:
        print(f"\nReading: {company} / {filename}")

        if filename.lower().endswith(".pdf"):
            text = read_pdf(file_path)
        elif filename.lower().endswith(".docx"):
            text = read_docx(file_path)
        else:
            continue

        if not text.strip():
            print(f"  No text extracted — skipping.")
            continue

        sanitised_text = sanitise_text(text)
        save_sanitised_preview(company, filename, sanitised_text)
        sanitised_items.append((company, filename, sanitised_text))

    if TEST_MODE:
        print("\nTEST_MODE enabled — skipping all Claude API calls.")
        return rows

    # Step 3: Send to Claude in batches
    total_batches = (len(sanitised_items) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"\nSending {len(sanitised_items)} files to Claude in {total_batches} batch(es) of up to {BATCH_SIZE}...\n")

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end   = start + BATCH_SIZE
        batch = sanitised_items[start:end]

        batch_labels = ", ".join(f"{c}/{f}" for c, f, _ in batch)
        print(f"Batch {batch_num + 1}/{total_batches}: [{batch_labels}]")

        try:
            results = extract_keywords_batch(batch)
        except Exception as e:
            print(f"  Batch failed: {e} — skipping this batch.")
            continue

        for company, filename, keywords in results:
            for category, items in keywords.items():
                for keyword in items:
                    rows.append({
                        "company":  company,
                        "file":     filename,
                        "category": category,
                        "keyword":  keyword
                    })

        print(f"  Batch {batch_num + 1} complete.")

    return rows


# =====================================================
# SAVE RESULTS
# =====================================================

def save_results(rows):
    if not rows:
        print("\nNo keyword data generated.")
        return

    df = pd.DataFrame(rows)
    df.to_csv("ai_keywords_detailed.csv", index=False)

    summary = (
        df.groupby(["category", "keyword"])
          .size()
          .reset_index(name="count")
          .sort_values(by="count", ascending=False)
    )
    summary.to_csv("ai_keywords_summary.csv", index=False)

    print("\nSaved:")
    print("  ai_keywords_detailed.csv")
    print("  ai_keywords_summary.csv")
    print(f"\nTotal keywords extracted: {len(rows)}")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":

    root_folder = r"C:\Users\prady\OneDrive\Desktop\Latest Job Search"

    if not os.path.exists(root_folder):
        raise FileNotFoundError(f"Folder not found: {root_folder}")

    rows = process_folder(root_folder)

    if not TEST_MODE:
        save_results(rows)# Write your code here :-)
