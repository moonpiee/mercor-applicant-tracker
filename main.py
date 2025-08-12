import argparse
import sys
import logging
import os
from dotenv import load_dotenv

main_logger = logging.getLogger(__name__)
main_logger.setLevel(logging.INFO)

main_log_file_path = 'main_orchestrator.log'
main_file_handler = logging.FileHandler(main_log_file_path)
main_file_handler.setLevel(logging.INFO)

main_console_handler = logging.StreamHandler()
main_console_handler.setLevel(logging.INFO)

main_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
main_file_handler.setFormatter(main_formatter)
main_console_handler.setFormatter(main_formatter)

main_logger.addHandler(main_file_handler)
main_logger.addHandler(main_console_handler)

load_dotenv()
try:
    from json_automation import compress_applicant_data, decompress_applicant_data
    from shortlist_automation import shortlist_applicant
    from llm_automation import evaluate_applicant_with_llm
except ImportError as e:
    main_logger.critical(f"Failed to import automation scripts. Ensure they are in the same directory and configured correctly: {e}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Trigger Mercor Applicant Tracking automations.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "action",
        choices=["compress", "decompress", "shortlist", "llm-evaluate", "all"],
        help="Specify the automation to run:\n"
             "  compress: Compress data for an applicant.\n"
             "  decompress: Decompress data for an applicant.\n"
             "  shortlist: Evaluate an applicant for shortlisting.\n"
             "  llm-evaluate: Evaluate an applicant using LLM.\n"
             "  all: Run compress, then shortlist, then llm-evaluate in sequence for an applicant."
    )
    parser.add_argument(
        "applicant_id",
        help="The Applicant ID (ex: 'APP001') to process."
    )

    args = parser.parse_args()
    action = args.action
    applicant_id = args.applicant_id

    main_logger.info(f"Triggering action: '{action}' for Applicant ID: '{applicant_id}'")
    success = True
    if action == "compress" or action == "all":
        main_logger.info(f"--- Running Compression for {applicant_id} ---")
        if not compress_applicant_data(applicant_id):
            main_logger.error(f"Compression failed for {applicant_id}.")
            success = False
            if action == "all": sys.exit(-1)
    if action == "shortlist" or (action == "all" and success):
        main_logger.info(f"--- Running Shortlisting for {applicant_id} ---")
        if not shortlist_applicant(applicant_id):
            main_logger.error(f"Shortlisting failed for {applicant_id}.")
            success = False
            if action == "all": sys.exit(-1)
    if action == "llm-evaluate" or (action == "all" and success):
        main_logger.info(f"--- Running LLM Evaluation for {applicant_id} ---")
        if not evaluate_applicant_with_llm(applicant_id):
            main_logger.error(f"LLM Evaluation failed for {applicant_id}.")
            success = False
            if action == "all": sys.exit(-1)
    if action == "decompress":
        main_logger.info(f"--- Running Decompression for {applicant_id} ---")
        if not decompress_applicant_data(applicant_id):
            main_logger.error(f"Decompression failed for {applicant_id}.")
            success = False
    if success:
        main_logger.info(f"Action '{action}' completed successfully for {applicant_id}.")
    else:
        main_logger.error(f"Action '{action}' failed for {applicant_id}.")
        sys.exit(-1)

if __name__ == "__main__":
    main()