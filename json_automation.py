import os
import json
from pyairtable import Api
from dotenv import load_dotenv
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_file_path = 'automation.log'
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
    logger.error("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")
    raise ValueError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in the .env file")

api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)

applicants_table = base.table("Applicants")
personal_details_table = base.table("Personal Details")
work_experience_table = base.table("Work Experience")
salary_preferences_table = base.table("Salary Preferences")


def get_first_linked_record_id(linked_field_value):
    if linked_field_value and isinstance(linked_field_value, list) and len(linked_field_value) > 0:
        first_item = linked_field_value[0]
        if isinstance(first_item, dict) and 'id' in first_item:
            return first_item['id']
        elif isinstance(first_item, str):
            return first_item
    return None

def get_all_linked_record_ids(linked_field_value):
    ids = []
    if linked_field_value and isinstance(linked_field_value, list):
        for item in linked_field_value:
            if isinstance(item, dict) and 'id' in item:
                ids.append(item['id'])
            elif isinstance(item, str):
                ids.append(item)
    return ids

def compress_applicant_data(applicant_id_text):
    logger.info(f"Attempting to compress data for Applicant ID: {applicant_id_text} ...")
    applicant_records = applicants_table.all(formula=f"{{Applicant ID}} = '{applicant_id_text}'")
    if not applicant_records:
        logger.error(f"Error: Applicant with ID '{applicant_id_text}' not found in 'Applicants' table.")
        return False
    applicant_record = applicant_records[0]
    applicant_record_id = applicant_record['id']
    logger.debug(f"Applicant record: {applicant_record}")
    compressed_data = {
        "personal": {},
        "experience": [],
        "salary": {}
    }
    personal_record_id = get_first_linked_record_id(applicant_record.get('fields', {}).get('Personal Details'))
    logger.debug(f"Personal Record ID: {personal_record_id} for Applicant ID: {applicant_id_text}")
    if personal_record_id:
        try:
            personal_record = personal_details_table.get(personal_record_id)
            if personal_record:
                fields = personal_record['fields']
                compressed_data["personal"] = {
                    "name": fields.get("Full Name"),
                    "email": fields.get("Email"),
                    "location": fields.get("Location"),
                    "linkedin": fields.get("LinkedIn")
                }
            else:
                logger.warning(f"Personal Details record not found for ID {personal_record_id}.")
        except Exception as e:
            logger.error(f"Error fetching Personal Details for ID {personal_record_id}: {e}")
    else:
        logger.warning(f"No Personal Details linked for Applicant ID {applicant_id_text}.")

    work_experience_linked_ids = get_all_linked_record_ids(applicant_record.get('fields', {}).get('Work Experience'))
    if work_experience_linked_ids:
        formula_parts = [f"RECORD_ID()='{rec_id}'" for rec_id in work_experience_linked_ids]
        work_experience_formula = "OR(" + ", ".join(formula_parts) + ")" if formula_parts else ""
        if work_experience_formula:
            try:
                work_records_raw = work_experience_table.all(formula=work_experience_formula)
                work_records_map = {rec['id']: rec for rec in work_records_raw if rec}
                for link_id in work_experience_linked_ids:
                    work_record = work_records_map.get(link_id)
                    if work_record:
                        fields = work_record['fields']
                        compressed_data["experience"].append({
                            "company": fields.get("Company"),
                            "title": fields.get("Title"),
                            "start_date": fields.get("Start Date"),
                            "end_date": fields.get("End Date"),
                            "technologies": fields.get("Technologies", [])
                        })
                    else:
                        logger.warning(f"Work Experience record not found for ID {link_id}.")
            except Exception as e:
                logger.error(f"Error fetching Work Experience records with formula '{work_experience_formula}': {e}")
        else:
            logger.warning(f"No valid Work Experience IDs to construct formula for Applicant ID {applicant_id_text}.")
    else:
        logger.warning(f"No Work Experience linked for Applicant ID {applicant_id_text}.")

    salary_record_id = get_first_linked_record_id(applicant_record.get('fields', {}).get('Salary Preferences'))
    if salary_record_id:
        try:
            salary_record = salary_preferences_table.get(salary_record_id)
            if salary_record:
                fields = salary_record['fields']
                compressed_data["salary"] = {
                    "preferred_rate": fields.get("Preferred Rate"),
                    "minimum_rate": fields.get("Minimum Rate"),
                    "currency": fields.get("Currency"),
                    "availability_hrs_wk": fields.get("Availability (hrs/wk)")
                }
            else:
                logger.warning(f"Salary Preferences record not found for ID {salary_record_id}.")
        except Exception as e:
            logger.error(f"Error fetching Salary Preferences for ID {salary_record_id}: {e}")
    else:
        logger.warning(f"No Salary Preferences linked for Applicant ID {applicant_id_text}.")

    try:
        json_string = json.dumps(compressed_data, indent=2)
        applicants_table.update(applicant_record_id, {"Compressed JSON": json_string})
        logger.info(f"Successfully compressed data for Applicant ID: {applicant_id_text}")
        return True
    except Exception as e:
        logger.error(f"Error updating 'Compressed JSON' for {applicant_id_text}: {e}")
        return False

def decompress_applicant_data(applicant_id_text: str):
    logger.info(f"Attempting to decompress data for Applicant ID: {applicant_id_text}")

    applicant_records = applicants_table.all(formula=f"{{Applicant ID}} = '{applicant_id_text}'")
    if not applicant_records:
        logger.error(f"Error: Applicant with ID '{applicant_id_text}' not found in 'Applicants' table.")
        return False
    applicant_record = applicant_records[0]
    applicant_record_id = applicant_record['id']
    compressed_json_str = applicant_record['fields'].get('Compressed JSON')
    if not compressed_json_str:
        logger.info(f"No 'Compressed JSON' found for Applicant ID: {applicant_id_text}. Skipping decompression.")
        return False
    try:
        data = json.loads(compressed_json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON for Applicant ID {applicant_id_text}: {e}")
        return False

    def link_child_to_applicant(child_table_obj, child_record_id, applicant_rec_id):
        try:
            child_table_obj.update(child_record_id, {"Applicant ID": [{"id": applicant_rec_id}]})
            logger.debug(f"Linked record {child_record_id} to {applicant_id_text}")
        except Exception as e:
            logger.error(f"Error linking record {child_record_id} to {applicant_id_text}: {e}")

    personal_data = data.get("personal", {})
    if personal_data:
        personal_linked_id = get_first_linked_record_id(applicant_record.get('fields', {}).get('Personal Details'))
        logger.debug(f"Personal Linked ID: {personal_linked_id}")
        new_personal_fields = {
            "Full Name": personal_data.get("name"),
            "Email": personal_data.get("email"),
            "Location": personal_data.get("location"),
            "LinkedIn": personal_data.get("linkedin")
        }
        new_personal_fields = {k: v for k, v in new_personal_fields.items() if v is not None}
        logger.debug(f"New Personal Fields: {new_personal_fields}")
        current_personal_record_id = None
        try:
            if personal_linked_id:
                logger.debug(f"Updating Personal Details record {personal_linked_id}.")
                personal_details_table.update(personal_linked_id, new_personal_fields)
                logger.info(f"Updated Personal Details for {applicant_id_text}.")
                current_personal_record_id = personal_linked_id
            else:
                new_record = personal_details_table.create(new_personal_fields)
                current_personal_record_id = new_record['id']
                link_child_to_applicant(personal_details_table, current_personal_record_id, applicant_record_id)
                logger.info(f"Created new Personal Details for {applicant_id_text}.")
        except Exception as e:
            logger.error(f"Error during Personal Details upsert for {applicant_id_text}: {e}")

    experience_data = data.get("experience", [])
    current_linked_experience_ids_from_applicant = get_all_linked_record_ids(
        applicant_record.get('fields', {}).get('Work Experience')
    )
    current_experience_records = []
    if current_linked_experience_ids_from_applicant:
        formula_parts = [f"RECORD_ID()='{rec_id}'" for rec_id in current_linked_experience_ids_from_applicant]
        work_experience_formula = "OR(" + ", ".join(formula_parts) + ")"
        try:
            current_experience_records = work_experience_table.all(formula=work_experience_formula)
        except Exception as e:
            logger.error(f"Error fetching current Work Experience records for decompression: {e}")

    current_experience_map = {
        (rec['fields'].get('Company'), rec['fields'].get('Title')): rec['id']
        for rec in current_experience_records
    }

    processed_experience_ids = set()

    for exp_item in experience_data:
        company = exp_item.get("company")
        title = exp_item.get("title")
        key = (company, title)

        if company is None or title is None:
            logger.warning(f"Skipping work experience item due to missing Company or Title: {exp_item}")
            continue

        new_exp_fields = {
            "Company": company,
            "Title": title,
            "Start Date": exp_item.get("start_date"),
            "End Date": exp_item.get("end_date"),
            "Technologies": exp_item.get("technologies")
        }
        new_exp_fields = {k: v for k, v in new_exp_fields.items() if v is not None}

        try:
            record_id = None
            if key in current_experience_map:
                record_id = current_experience_map[key]
                work_experience_table.update(record_id, new_exp_fields)
                processed_experience_ids.add(record_id)
                logger.debug(f"Updated Work Experience record {record_id} for {applicant_id_text}.")
            else:
                new_record = work_experience_table.create(new_exp_fields)
                record_id = new_record['id']
                link_child_to_applicant(work_experience_table, record_id, applicant_record_id)
                processed_experience_ids.add(record_id)
                logger.debug(f"Created new Work Experience record {record_id} for {applicant_id_text}.")
        except Exception as e:
            logger.error(f"Error during Work Experience upsert for {applicant_id_text} (Company: {company}, Title: {title}): {e}")

    to_delete_ids = [
        rec_id for rec_id in current_linked_experience_ids_from_applicant
        if rec_id not in processed_experience_ids
    ]
    if to_delete_ids:
        try:
            work_experience_table.batch_delete(to_delete_ids)
            logger.info(f"Deleted {len(to_delete_ids)} old Work Experience records for {applicant_id_text}.")
        except Exception as e:
            logger.error(f"Error deleting old Work Experience records for {applicant_id_text}: {e}")

    salary_data = data.get("salary", {})
    if salary_data:
        salary_linked_id = get_first_linked_record_id(applicant_record.get('fields', {}).get('Salary Preferences'))
        new_salary_fields = {
            "Preferred Rate": salary_data.get("preferred_rate"),
            "Minimum Rate": salary_data.get("minimum_rate"),
            "Currency": salary_data.get("currency"),
            "Availability (hrs/wk)": salary_data.get("availability_hrs_wk")
        }
        new_salary_fields = {k: v for k, v in new_salary_fields.items() if v is not None}

        current_salary_record_id = None
        try:
            if salary_linked_id:
                salary_preferences_table.update(salary_linked_id, new_salary_fields)
                logger.info(f"Updated Salary Preferences for {applicant_id_text}.")
                current_salary_record_id = salary_linked_id
            else:
                new_record = salary_preferences_table.create(new_salary_fields)
                current_salary_record_id = new_record['id']
                link_child_to_applicant(salary_preferences_table, current_salary_record_id, applicant_record_id)
                logger.info(f"Created new Salary Preferences for {applicant_id_text}.")

        except Exception as e:
            logger.error(f"Error during Salary Preferences upsert for {applicant_id_text}: {e}")

    logger.info(f"Successfully decompressed data for Applicant ID: {applicant_id_text}")
    return True
