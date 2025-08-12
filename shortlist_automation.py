import os
import json
import logging
from pyairtable import Api
from dotenv import load_dotenv
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_file_path = 'shortlist_automation.log'
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

if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
    logger.critical("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")
    raise ValueError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")

api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)

applicants_table = base.table("Applicants")
shortlisted_leads_table = base.table("Shortlisted Leads")

TIER_1_COMPANIES = ["Google", "Meta", "OpenAI", "Microsoft", "Amazon", "Apple", "Netflix", "Tesla"]
APPROVED_LOCATIONS = {"us", "canada", "uk", "germany", "india"}


def calculate_experience_years(experience_list):
    total_years = 0
    tier_1_company_present = False
    for exp in experience_list:
        start_date_str = exp.get("start_date")
        end_date_str = exp.get("end_date")
        company = exp.get("company", "")
        if company:
            if any(c.lower() == company.lower() for c in TIER_1_COMPANIES):
                tier_1_company_present = True
        try:
            if start_date_str:
                start = datetime.strptime(start_date_str, "%Y-%m-%d")
                end = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else datetime.now()
                if start > end:
                    logger.warning(f"Experience data error: Start date {start_date_str} after end date {end_date_str} for {company}. Skipping calculation for this entry.")
                    continue
                duration = end - start
                total_years += duration.days / 365.25
            else:
                logger.warning(f"Experience entry missing start_date: {exp}. Skipping this entry for total years calculation.")
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse date for experience entry {exp}: {e}. Skipping calculation for this entry.")
            continue
    return total_years, tier_1_company_present

def shortlist_applicant(applicant_id_text: str):
    logger.info(f"Evaluating applicant for shortlisting: {applicant_id_text}")
    applicant_records = applicants_table.all(formula=f"{{Applicant ID}} = '{applicant_id_text}'")
    if not applicant_records:
        logger.error(f"Applicant with ID '{applicant_id_text}' not found in 'Applicants' table.")
        return False
    applicant_record = applicant_records[0]
    applicant_record_id = applicant_record['id']
    applicant_primary_id_value = applicant_record['fields'].get('Applicant ID') 

    logger.info(f"Fetched Applicant Record ID for {applicant_id_text}: {applicant_record_id}")
    logger.info(f"Fetched Applicant Primary ID Value for {applicant_id_text}: {applicant_primary_id_value}")
    compressed_json_str = applicant_record['fields'].get('Compressed JSON')
    if not compressed_json_str:
        logger.warning(f"No 'Compressed JSON' found for Applicant ID: {applicant_id_text}. Cannot shortlist.")
        applicants_table.update(applicant_record_id, {"Shortlist Status": "Incomplete Data"})
        return False
    try:
        data = json.loads(compressed_json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON for Applicant ID {applicant_id_text}: {e}")
        applicants_table.update(applicant_record_id, {"Shortlist Status": "JSON Error"})
        return False
    personal_data = data.get("personal", {})
    experience_data = data.get("experience", [])
    salary_data = data.get("salary", {})

    score_reasons = []
    is_shortlisted = True

    total_experience_years, tier_1_company_present = calculate_experience_years(experience_data)
    experience_criteria_met = (total_experience_years >= 4) or tier_1_company_present
    if experience_criteria_met:
        reason = f"Experience: {total_experience_years:.1f} years total"
        if tier_1_company_present:
            reason += " (includes Tier-1 company)"
        score_reasons.append(reason)
    else:
        is_shortlisted = False
        score_reasons.append(
            f"FAILED: Experience ({total_experience_years:.1f} years, Tier-1: {tier_1_company_present}) - min 4 years OR Tier-1 required."
        )
    preferred_rate = salary_data.get("preferred_rate")
    currency = salary_data.get("currency")
    availability = salary_data.get("availability_hrs_wk")
    compensation_criteria_met_individual = True
    comp_reason_parts = []

    if preferred_rate is not None and currency == "USD":
        if preferred_rate <= 100:
            comp_reason_parts.append(f"Preferred Rate: ${preferred_rate} USD/hour")
        else:
            compensation_criteria_met_individual = False
            comp_reason_parts.append(f"Preferred Rate: ${preferred_rate} USD/hour (FAILED - must be <= $100)")
    else:
        compensation_criteria_met_individual = False
        if preferred_rate is None or currency is None:
            comp_reason_parts.append("Preferred Rate: Missing or invalid (FAILED)")
        else:
            comp_reason_parts.append(f"Preferred Rate: {preferred_rate} {currency}/hour (FAILED - only USD <= $100 accepted)")
    if availability is not None and availability >= 20:
        comp_reason_parts.append(f"Availability: {availability} hrs/week")
    else:
        compensation_criteria_met_individual = False
        if availability is None:
            comp_reason_parts.append("Availability: Missing or invalid (FAILED)")
        else:
            comp_reason_parts.append(f"Availability: {availability} hrs/week (FAILED - must be >= 20)")

    if compensation_criteria_met_individual:
        score_reasons.append("Compensation: " + ", ".join(comp_reason_parts))
    else:
        is_shortlisted = False
        score_reasons.append("FAILED: Compensation - " + ", ".join(comp_reason_parts))

    applicant_location = personal_data.get("location", "")
    location_criteria_met = False
    location_match_found = "None"
    if applicant_location:
        for approved_loc_keyword in APPROVED_LOCATIONS:
            if approved_loc_keyword in applicant_location.lower():
                location_criteria_met = True
                location_match_found = approved_loc_keyword
                break
    if location_criteria_met:
        score_reasons.append(f"Location: '{applicant_location}' (Approved: matched '{location_match_found}')")
    else:
        is_shortlisted = False
        score_reasons.append(f"FAILED: Location ('{applicant_location}') - not in approved list.")

    new_status = "Shortlisted" if is_shortlisted else "Not Shortlisted"
    applicants_table.update(applicant_record_id, {"Shortlist Status": new_status})
    logger.info(f"Applicant {applicant_id_text} Shortlist Status set to: {new_status}")
    logger.info(f"Score Reason: {score_reasons}")

    if is_shortlisted:
        formula_str = f"{{Applicant_ref}} = '{applicant_primary_id_value}'"
        
        existing_shortlist = shortlisted_leads_table.all(formula=formula_str)        
        shortlist_reason_text = "; ".join(score_reasons)

        fields_to_upsert = {
            "Applicant_ref": [applicant_record_id],
            "Compressed JSON": compressed_json_str,
            "Score Reason": shortlist_reason_text,
        }
        
        try:
            if existing_shortlist:
                shortlisted_leads_table.update(existing_shortlist[0]['id'], fields_to_upsert)
                logger.info(f"Updated existing Shortlisted Lead record for {applicant_id_text}.")
            else:
                shortlisted_leads_table.create(fields_to_upsert)
                logger.info(f"Created new Shortlisted Lead record for {applicant_id_text}.")
            return True
        except Exception as e:
            logger.error(f"Error creating/updating Shortlisted Lead record for {applicant_id_text}: {e}")
            return False
