import pandas as pd
import re
import os

# =====================================================
# SETTINGS — update these paths before running
# =====================================================

RESUME_KEYWORDS_PATH = r""
APIFY_JD_PATH        = r""
OUTPUT_DIR           = r""

# =====================================================
# STEP 1 — LOAD RAW FILES
# =====================================================

print("Loading files...")

resume_df = pd.read_csv(RESUME_KEYWORDS_PATH)
jd_df     = pd.read_csv(APIFY_JD_PATH)

print(f"  Resume keywords loaded: {len(resume_df)} rows")
print(f"  Apify JD records loaded: {len(jd_df)} rows")

# =====================================================
# STEP 2 — STANDARDISE RESUME KEYWORDS
# Incoming columns: company, file, category, keyword
# =====================================================

print("\nStandardising resume keyword CSV...")

resume_standard = pd.DataFrame({
    "keyword":     resume_df["keyword"].str.strip().str.lower(),
    "category":    resume_df["category"].str.strip().str.lower(),
    "source_type": "resume",
    "source_name": resume_df["company"].str.strip(),
    "url":         "",
    "platform":    "local",
    "job_title":   "",
    "raw_text":    ""
})

# =====================================================
# STEP 3 — STANDARDISE APIFY JD CSV
# Incoming columns: url, jobTitle, company, jobDescription
# Note: Apify uses camelCase from the pageFunction output
# =====================================================

print("Standardising Apify JD CSV...")

# Handle both camelCase (direct Apify export) and
# snake_case (if downloaded via Apify dataset CSV)
def get_col(df, *candidates):
    for c in candidates:
        if c in df.columns:
            return df[c]
    raise KeyError(f"None of {candidates} found in columns: {list(df.columns)}")

jd_standard = pd.DataFrame({
    "keyword":     "",   # filled after keyword extraction below
    "category":    "",   # filled after keyword extraction below
    "source_type": "jd",
    "source_name": (
        get_col(jd_df, "jobTitle", "job_title").str.strip()
        + " at " +
        get_col(jd_df, "company", "Company").str.strip()
    ),
    "url":         get_col(jd_df, "url", "URL").str.strip(),
    "platform":    get_col(jd_df, "url", "URL").apply(
                       lambda x: "seek" if "seek.com" in str(x)
                                 else "linkedin" if "linkedin.com" in str(x)
                                 else "indeed" if "indeed.com" in str(x)
                                 else "unknown"
                   ),
    "job_title":   get_col(jd_df, "jobTitle", "job_title").str.strip(),
    "raw_text":    get_col(jd_df, "jobDescription", "job_description").str.strip()
})

# =====================================================
# STEP 4 — EXTRACT KEYWORDS FROM JD RAW TEXT
# Uses simple rule-based extraction as a lightweight
# alternative to calling Claude for every JD row.
# Replace this section with a Claude API call if you
# want AI-classified JD keywords instead.
# =====================================================

print("Extracting keywords from JD text...")

# Common ATS keyword signals — expand this list as needed
TECH_SKILLS   = ["sql","python","excel","power bi","tableau","machine learning",
                  "data analysis","financial modelling","forecasting","reporting",
                  "statistical analysis","data visualisation","etl","modelling"]

TOOLS         = ["salesforce","jira","sap","hubspot","google analytics","looker",
                 "snowflake","dbt","airflow","powerpoint","sharepoint","confluence",
                 "asana","trello","notion"]

SOFT_SKILLS   = ["stakeholder management","communication","leadership","collaboration",
                 "problem solving","adaptability","attention to detail","critical thinking",
                 "time management","presentation","negotiation","mentoring"]

METHODOLOGIES = ["agile","scrum","kanban","prince2","six sigma","waterfall",
                 "design thinking","okrs","lean","devops","ci/cd"]

DOMAIN_TERMS  = ["p&l","revenue","churn","saas","b2b","b2c","ats","kpi","roi",
                 "nps","mrr","arr","working capital","ebitda","go-to-market",
                 "pipeline","customer success","product roadmap"]

CATEGORY_MAP = {
    "technical_skills": TECH_SKILLS,
    "tools":            TOOLS,
    "soft_skills":      SOFT_SKILLS,
    "methodologies":    METHODOLOGIES,
    "domain_terms":     DOMAIN_TERMS
}

jd_keyword_rows = []

for _, row in jd_standard.iterrows():
    text = str(row["raw_text"]).lower()
    for category, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw in text:
                jd_keyword_rows.append({
                    "keyword":     kw,
                    "category":    category,
                    "source_type": "jd",
                    "source_name": row["source_name"],
                    "url":         row["url"],
                    "platform":    row["platform"],
                    "job_title":   row["job_title"],
                    "raw_text":    ""
                })

jd_keywords_df = pd.DataFrame(jd_keyword_rows)
print(f"  JD keywords extracted: {len(jd_keywords_df)} rows")

# =====================================================
# STEP 5 — MERGE BOTH STANDARDISED DATASETS
# =====================================================

print("\nMerging datasets...")

merged = pd.concat([resume_standard, jd_keywords_df], ignore_index=True)

# =====================================================
# STEP 6 — AGGREGATE & ADD FLAGS
# =====================================================

print("Aggregating and flagging...")

# Count occurrences per keyword + category + source_type
agg = (
    merged
    .groupby(["keyword", "category", "source_type"])
    .size()
    .reset_index(name="count")
)

# Pivot to get resume and jd counts side by side
pivot = agg.pivot_table(
    index=["keyword", "category"],
    columns="source_type",
    values="count",
    fill_value=0
).reset_index()

pivot.columns.name = None

# Ensure both columns exist even if one source has no data
if "resume" not in pivot.columns:
    pivot["resume"] = 0
if "jd" not in pivot.columns:
    pivot["jd"] = 0

pivot.rename(columns={"resume": "resume_count", "jd": "jd_count"}, inplace=True)

pivot["appears_in_resume"] = pivot["resume_count"] > 0
pivot["appears_in_jd"]     = pivot["jd_count"] > 0

pivot = pivot.sort_values("jd_count", ascending=False).reset_index(drop=True)

# =====================================================
# STEP 7 — GAP ANALYSIS
# Keywords in JDs but missing from resumes
# =====================================================

print("Running gap analysis...")

gap = pivot[
    (pivot["appears_in_jd"] == True) &
    (pivot["appears_in_resume"] == False)
].copy()

gap = gap.sort_values("jd_count", ascending=False).reset_index(drop=True)

print(f"  Total unique keywords: {len(pivot)}")
print(f"  Gap keywords (in JDs, missing from resumes): {len(gap)}")

# =====================================================
# STEP 8 — SAVE OUTPUTS
# =====================================================

print("\nSaving outputs...")

unified_path = os.path.join(OUTPUT_DIR, "unified_keyword_intelligence.csv")
gap_path     = os.path.join(OUTPUT_DIR, "gap_analysis.csv")
merged_path  = os.path.join(OUTPUT_DIR, "merged_all_keywords.csv")

pivot.to_csv(unified_path, index=False)
gap.to_csv(gap_path, index=False)
merged.to_csv(merged_path, index=False)

print(f"  unified_keyword_intelligence.csv — {len(pivot)} rows")
print(f"  gap_analysis.csv — {len(gap)} rows")
print(f"  merged_all_keywords.csv — {len(merged)} rows")
print("\nDone.")

# =====================================================
# STEP 9 — FINAL SINGLE CSV
# One clean master file combining everything
# =====================================================

print("Building final master CSV...")

final = pivot.copy()

# Add gap flag as a readable column
final["gap_keyword"] = (
    (final["appears_in_jd"] == True) &
    (final["appears_in_resume"] == False)
)

# Add priority score — higher JD count + gap = higher priority
final["priority_score"] = final.apply(
    lambda row: row["jd_count"] * 2 if row["gap_keyword"] else row["jd_count"],
    axis=1
)

# Sort by priority
final = final.sort_values("priority_score", ascending=False).reset_index(drop=True)

# Clean column order for readability
final = final[[
    "keyword",
    "category",
    "jd_count",
    "resume_count",
    "appears_in_jd",
    "appears_in_resume",
    "gap_keyword",
    "priority_score"
]]

final_path = os.path.join(OUTPUT_DIR, "master_keyword_intelligence.csv")
final.to_csv(final_path, index=False)

print(f"  master_keyword_intelligence.csv — {len(final)} rows")
print("\nAll done.")

# =====================================================
# STEP 10 — EXPORT QUERY-READY KEYWORD FILE FOR n8n
# =====================================================

print("Building query-ready export for n8n...")

# Take only gap keywords with highest priority
query_ready = final[final["gap_keyword"] == True].copy()

# Take top 20 by priority score — enough for meaningful queries
# without overloading Apify with too many runs
query_ready = query_ready.head(20)

# Group by category so n8n can build targeted queries per skill type
query_ready = query_ready[[
    "keyword",
    "category",
    "priority_score",
    "jd_count"
]]

query_path = os.path.join(OUTPUT_DIR, "n8n_query_input.csv")
query_ready.to_csv(query_path, index=False)

print(f"  n8n_query_input.csv — {len(query_ready)} rows")
print("  Ready to feed into n8n workflow.")
