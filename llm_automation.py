import os
import json
import time
import logging
from pyairtable import Api
from dotenv import load_dotenv
from datetime import datetime, timedelta
from groq import Groq, APIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_file_path = 'llm_automation.log'
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
    logger.critical("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")
    raise ValueError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")
if not GROQ_API_KEY:
    logger.critical("GROQ_API_KEY must be set in the .env file")
    raise ValueError("GROQ_API_KEY must be set in the .env file")

api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)

applicants_table = base.table("Applicants")

LLM_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
MAX_TOKENS_PER_CALL = int(os.getenv("MAX_TOKENS_PER_CALL", 1000))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", 3))
INITIAL_BACKOFF_DELAY = float(os.getenv("LLM_INITIAL_BACKOFF_DELAY", 1))

groq_client = Groq(api_key=GROQ_API_KEY)
logger.info(f"Groq client initialised: {groq_client}")

def parse_llm_response(response_text):
    summary = ""
    score = None
    issues = "None"
    follow_ups = []
    capture_summary = False
    capture_follow_ups = False
    lines = [line.strip() for line in response_text.split('\n') if line.strip()]

    for line in lines:
        lower_line = line.lower()
        if lower_line.startswith("summary:"):
            summary = line[len("Summary:"):].strip()
            capture_summary = True
            capture_follow_ups = False
        elif lower_line.startswith("score:"):
            score_str = line[len("Score:"):].strip()
            try:
                score = int(score_str)
            except ValueError:
                logger.warning(f"LLM returned non-integer score: '{score_str}'")
                score = None
            capture_summary = False
            capture_follow_ups = False
        elif lower_line.startswith("issues:"):
            issues = line[len("Issues:"):].strip()
            capture_summary = False
            capture_follow_ups = False
        elif lower_line.startswith("follow-ups:"):
            capture_follow_ups = True
            capture_summary = False
        elif capture_summary:
            summary += " " + line.strip()
        elif capture_follow_ups and line.startswith("•"):
            follow_ups.append(line.strip())
        elif capture_follow_ups and not line.startswith("•"):
            capture_follow_ups = False
    return {
        "summary": summary.strip(),
        "score": score,
        "issues": issues.strip(),
        "follow_ups": "\n".join(follow_ups).strip()
    }


def evaluate_applicant_with_llm(applicant_id_text):
    logger.info(f"Evaluating applicant with LLM: {applicant_id_text} ...")

    applicant_records = applicants_table.all(formula=f"{{Applicant ID}} = '{applicant_id_text}'")
    if not applicant_records:
        logger.error(f"Applicant with ID '{applicant_id_text}' not found in 'Applicants' table.")
        return False
    applicant_record = applicant_records[0]
    applicant_record_id = applicant_record['id']
    applicant_fields = applicant_record['fields']

    compressed_json_str = applicant_fields.get('Compressed JSON')
    if not compressed_json_str:
        logger.warning(f"No 'Compressed JSON' found for Applicant ID: {applicant_id_text}. Skipping LLM evaluation.")
        return False

    last_compressed_time_str = applicant_fields.get('Last Modified')
    last_llm_evaluated_time_str = applicant_fields.get('LLM Last Evaluated')

    last_compressed_dt = None
    last_llm_evaluated_dt = None

    try:
        if last_compressed_time_str:
            last_compressed_dt = datetime.fromisoformat(last_compressed_time_str.replace('Z', '+00:00'))
        if last_llm_evaluated_time_str:
            last_llm_evaluated_dt = datetime.fromisoformat(last_llm_evaluated_time_str.replace('Z', '+00:00'))
    except ValueError as e:
        logger.warning(f"Warning: Could not parse timestamp for {applicant_id_text}: {e}. Proceeding with evaluation.")
        last_compressed_dt = datetime.min
        last_llm_evaluated_dt = datetime.min

    if last_llm_evaluated_dt and last_compressed_dt and last_llm_evaluated_dt >= last_compressed_dt:
        logger.info(f"Compressed JSON for {applicant_id_text} has not changed since last LLM evaluation ({last_llm_evaluated_dt}). Skipping.")
        return True

    prompt = f"""You are a recruiting analyst. Given this JSON applicant profile, do four things:
    1. Provide a concise 75-word summary.
    2. Rate overall candidate quality from 1-10 (higher is better).
    3. List any data gaps or inconsistencies you notice.
    4. Suggest up to three follow-up questions to clarify gaps.

    Return exactly:
    Summary: <text>
    Score: <integer>
    Issues: <comma-separated list or 'None'>
    Follow-Ups: <bullet list>

    Applicant JSON Profile:
    ```json
    {compressed_json_str}
    """
    llm_response_content = None
    retries = 0
    delay = INITIAL_BACKOFF_DELAY
    while retries < MAX_RETRIES:
        try:
            logger.info(f"Making LLM call for {applicant_id_text} (Attempt {retries + 1}/{MAX_RETRIES}). Model: {LLM_MODEL}")
            response = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a helpful recruiting analyst assistant."},
                    {"role": "user", "content": prompt}
                ],
                model=LLM_MODEL,
                max_tokens=MAX_TOKENS_PER_CALL,
                temperature=0.7
            )
            llm_response_content = response.choices[0].message.content.strip()
            logger.info(f"LLM response received for {applicant_id_text}.")
            break
        except APIError as e:
            logger.error(f"Groq API error for {applicant_id_text} (Status: {e.status_code}): {e}")
            retries += 1
            if retries < MAX_RETRIES:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Max retries reached for {applicant_id_text}. LLM evaluation failed.")
                return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during LLM call for {applicant_id_text}: {e}")
            return False

    if not llm_response_content:
        logger.error(f"No LLM response content after retries for {applicant_id_text}. Cannot update Airtable.")
        return False

    parsed_outputs = parse_llm_response(llm_response_content)

    updates = {
        "LLM Summary": parsed_outputs["summary"],
        "LLM Score": parsed_outputs["score"],
        "LLM Follow-Ups": parsed_outputs["follow_ups"],
        "LLM Last Evaluated": datetime.now().isoformat() + "Z"
    }
    if parsed_outputs["issues"] and parsed_outputs["issues"].lower() != 'none':
        logger.warning(f"LLM identified issues for {applicant_id_text}: {parsed_outputs['issues']}")

    try:
        applicants_table.update(applicant_record_id, updates)
        logger.info(f"Successfully updated LLM fields for Applicant ID: {applicant_id_text}")
        return True
    except Exception as e:
        logger.error(f"Error updating LLM fields for {applicant_id_text}: {e}")
        return False
