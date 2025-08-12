# Mercor Applicant Tracker: Airtable Multi-Table Form + JSON Automation Solution
###### Developer: CHANDANA JUTTU

This project implements an Airtable-based data model and Python automation system for contractor application management, as specified in the Mercor Mini-Interview Task doc.

## Deliverables

### Airtable Base:
- **Link**: https://airtable.com/invite/l?inviteId=invh7GbjW8qrmcn5G&inviteToken=6a857f9e7f3138c5c6615c3769ea28edd727e2c0c226ac17ccbfb85c3946ac5d&utm_medium=email&utm_source=product_team&utm_content=transactional-alerts

### Python Automation Scripts:
- **`main.py`**: Main Wrapper & Orchestrator to trigger individual automations from the command line.
- **`json_automation.py`**: Handles data compression from Airtable tables into a single JSON object and decompressions into child tables if any edits.
- **`shortlist_automation.py`**: Automates candidate shortlisting based on predefined criteria (as given).
- **`llm_automation.py`**: Integrates with a Groq LLM endpoint(also integrable with OPENAPI) for application evaluation and enrichment.

## Setup Instructions

To set up and run the automation scripts locally:

### 1. Clone the Repository / Unzip Package:

```bash
git clone https://github.com/moonpiee/mercor-applicant-tracker.git
cd mercor-applicant-tracker
(If unzipping you canjust navigate to the extracted folder.)
```

### 2. Setup Virtual Environment

```bash
python -m venv venv
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables:

Create a `.env` file in root directory. Copy the structure from `.env.example` and fill in your actual API keys, LLM options and Airtable Base ID:

```env
AIRTABLE_API_KEY="YOUR_AIRTABLE_API_KEY"
AIRTABLE_BASE_ID="YOUR_AIRTABLE_BASE_ID"
GROQ_API_KEY="YOUR_GROQ_API_KEY"
# Optional LLM settings (e.g., GROQ_MODEL="llama-3.1-8b-instant")
```
### 5. Airtable Base (manual):

The provided Airtable base (link above) is pre-configured with the required tables and fields:

**Tables**: Applicants, Personal Details, Work Experience, Salary Preferences, Shortlisted Leads.(as mentioned in doc)

**Linked Fields**: Child tables (Personal Details, Work Experience, Salary Preferences) link back to Applicants via a field named `Applicant ID`. The Shortlisted Leads table links to Applicants via a field named `Applicant_ref`.

## How to Run Automations

All automations can be triggered via the `main.py` orchestrator script using command-line arguments. Logs for each specific automation will be generated in separate `.log` files (`json_automation.log`, `shortlist_automation.log`, `llm_automation.log`), and `main_orchestrator.log` will track overall execution.

### Usage:

```bash
python main.py <action> <applicant_id>
```

**`<action>` options:**
- `compress`: Collects and compresses applicant data into Compressed JSON.
- `decompress`: Decompresses Compressed JSON back into child tables.
- `shortlist`: Evaluates applicant for shortlisting based oncriteria.
- `llm-evaluate`: Runs LLM evaluation (summary, score, follow-ups).
- `all`: Runs compress, then shortlist, then llm-evaluate all in sequence.

**`<applicant_id>`**: The Applicant ID (e.g., APP001) from the Applicants table to process.

### Sample:

```bash
python main.py compress APP001

python main.py shortlist APP002

python main.py llm-evaluate APP001

python main.py all APP001
```

## Automation Scripts Details

### JSON Automation
- Gathers data from Personal Details, Work Experience, Salary Preferences (linked to Applicants).
- Consolidates into Compressed JSON field in Applicants.
- Decompression performs the reverse for editing.

### Lead Shortlist Automation:
**Criteria:**
- **Experience**: ≥ 4 years total OR worked at a Tier-1 company (Google, Meta, OpenAI, etc.).
- **Compensation**: Preferred Rate ≤ $100 USD/hour AND Availability ≥ 20 hrs/week.
- **Location**: In US, Canada, UK, Germany, or India.

**Output**: Updates Shortlist Status in Applicants and creates/updates records in Shortlisted Leads with Score Reason as reason for selecting.

### LLM Evaluation & Enrichment:
- **LLM**: Groq API (used `llama-3.1-8b-instant` by default).
- **Output**: Populates LLM Summary (≤75 words), LLM Score (1-10), and LLM Follow-Ups (up to 3 questions) in Applicants.
- **Guardrails**: Includes retries with exponential backoff for API calls. Skips evaluation if Compressed JSON has not changed since the last LLM evaluation (tracked by LLM Last Evaluated field in Applicants Table).

## Extending or Customizing Shortlist Criteria

The shortlisting logic is defined within `shortlist_automation.py`. To extend or customize:

1. Open `shortlist_automation.py`.
2. Modify `TIER_1_COMPANIES`, `APPROVED_LOCATIONS`, or the logic within `shortlist_applicant` to adjust existing rules or add new criteria.
3. Additional metrics can be the projects that candidates worked on, strength at each skill, awards/recognitions obtained.

## Security

- Ensured API keys are stored in a `.env` file and are not hard-coded
- LLM integration includes budget guardrails (like token limits, re-evaluation checks toavoid regenerating for already compressed json) and robust error handling.

- All script activity is logged for auditing and debugging purposes.
