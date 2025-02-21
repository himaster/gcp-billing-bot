from datetime import date, timedelta
from google.cloud import bigquery
from google.oauth2 import service_account
import os
import requests
import json
import logging

SLACK_API_TOKEN = os.environ['SLACK_API_TOKEN']
SLACK_CHANNEL_ID = os.environ['SLACK_CHANNEL_ID']
BQ_TABLE = os.environ['BQ_TABLE']
SERVICE_ACCOUNT_FILE = "/var/secrets/billing-sa"

# --- Options controlled by environment variables ---
SEND_PROJECT_BREAKDOWN = os.getenv("SEND_PROJECT_BREAKDOWN", "false").lower() in ("true", "1", "yes")
SEND_THREAD_DETAILS = os.getenv("SEND_THREAD_DETAILS", "false").lower() in ("true", "1", "yes")

logging.basicConfig(level=logging.INFO)

def send_slack_message(blocks, fallback_text="GCP Cost Report", thread_ts=None, channel_id=SLACK_CHANNEL_ID):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SLACK_API_TOKEN}"
    }
    final_channel = channel_id
    # If a user ID is passed (starts with "U"), open a direct message channel first.
    if channel_id.startswith("U"):
        open_payload = {"users": channel_id}
        try:
            open_response = requests.post("https://slack.com/api/conversations.open",
                                          data=json.dumps(open_payload),
                                          headers=headers)
            open_data = open_response.json()
            if open_data.get("ok"):
                final_channel = open_data["channel"]["id"]
            else:
                logging.error(f"Error opening DM: {open_data.get('error')}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error calling conversations.open: {e}")
    
    payload = {
        "channel": final_channel,
        "blocks": blocks,
        "text": fallback_text
    }
    if thread_ts is not None:
        payload["thread_ts"] = thread_ts
    payload_json = json.dumps(payload)
    try:
        response = requests.post("https://slack.com/api/chat.postMessage",
                                 data=payload_json,
                                 headers=headers)
        response_data = response.json()
        if not response_data.get("ok"):
            logging.error(f"Error sending message to Slack: {response_data.get('error')}")
            return None
        else:
            logging.info("Message successfully sent to Slack")
            return response_data.get("ts")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling Slack API: {e}")
        return None

# --- Function to build a text table ---
def build_table(header_names, rows, overall_label, overall_cost, overall_delta):
    max_lines = 34
    header_lines = 2  # header and separator
    footer_lines = 2  # separator and overall (TOTAL) row
    max_data_rows = max_lines - header_lines - footer_lines

    # Calculate column widths
    col_widths = []
    for i, col in enumerate(header_names):
        if not rows:
            col_width = len(col)
        else:
            col_width = max(len(col), *(len(str(row[i])) for row in rows))
        col_widths.append(col_width)

    header_line = "  ".join(header_names[i].ljust(col_widths[i]) for i in range(len(header_names)))
    separator = "-" * (sum(col_widths) + 2 * (len(col_widths) - 1))
    table_lines = [header_line, separator]

    # Limit the number of data rows so that the footer always fits
    if len(rows) > max_data_rows:
        rows = rows[:max_data_rows]
    for row in rows:
        line = "  ".join(str(row[i]).ljust(col_widths[i]) if i == 0 else str(row[i]).rjust(col_widths[i])
                         for i in range(len(row)))
        table_lines.append(line)

    # Build the overall row
    overall_line = f"{overall_label.ljust(col_widths[0])}  {overall_cost.rjust(col_widths[1])}"
    if len(header_names) > 2:
        overall_line += "  " + overall_delta.rjust(col_widths[2])
    
    table_lines.append(separator)
    table_lines.append(overall_line)
    
    # If the total number of lines exceeds max_lines, trim them (should not happen with proper limits)
    if len(table_lines) > max_lines:
        table_lines = table_lines[:max_lines]
    return "\n".join(table_lines)

# --- Main function ---
def get_gcp_cost(request):
    """
    Executes a BigQuery query to retrieve cost data for the day before yesterday and the day before that,
    broken down by project and SKU.
    It builds two blocks for the main message:
      1) A table aggregated by SKU across all projects with an OVERALL row.
      2) A table with totals by project.
    Then, in a thread to this message, it sends separate messages for each project with detailed SKU breakdown.
    Each block is limited to 30 lines (extra lines are trimmed, but the overall row is preserved).
    """
    try:
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
        client = bigquery.Client(credentials=credentials, project=credentials.project_id)
    except Exception as e:
        err_msg = f"Error authorizing with BigQuery: {e}"
        logging.error(err_msg)
        send_slack_message([{"type": "section", "text": {"type": "mrkdwn", "text": err_msg}}], fallback_text=err_msg)
        return "Error"

    # --- Compute the date (day before yesterday) ---
    cost_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")

    # --- BigQuery Query ---
    query = f"""
    WITH cost_data AS (
      SELECT 
        project.id AS project_id,
        sku.description AS service_name,
        DATE(usage_start_time) AS cost_date,
        SUM(cost) AS total_cost
      FROM {BQ_TABLE}
      WHERE DATE(usage_start_time) IN (CURRENT_DATE() - 2, CURRENT_DATE() - 3)
      GROUP BY project_id, service_name, cost_date
    )
    SELECT
      a.project_id,
      a.service_name,
      a.total_cost AS yesterday_cost,
      b.total_cost AS day_before_cost,
      CASE 
        WHEN b.total_cost IS NULL OR b.total_cost = 0 THEN NULL
        ELSE ROUND((a.total_cost - b.total_cost) / b.total_cost * 100)
      END AS delta_percentage
    FROM cost_data a
    LEFT JOIN cost_data b
      ON a.project_id = b.project_id 
      AND a.service_name = b.service_name 
      AND b.cost_date = CURRENT_DATE() - 3
    WHERE a.cost_date = CURRENT_DATE() - 2
    ORDER BY a.project_id, yesterday_cost DESC
    """
    
    try:
        query_job = client.query(query)
        result = query_job.result()
        
        # --- Data Aggregation ---
        overall_total_yesterday = 0.0
        overall_total_day_before = 0.0
        
        projects = {}      # Detailed breakdown by project (for thread messages)
        sku_agg = {}       # Aggregated breakdown by SKU (across projects)
        project_totals = {}# Totals by project
        
        for r in result:
            project = r.project_id
            overall_total_yesterday += r.yesterday_cost
            overall_total_day_before += (r.day_before_cost or 0)
            if project not in projects:
                projects[project] = {"rows": [], "total_yesterday": 0.0, "total_day_before": 0.0}
            service = r.service_name[:45]  # Trim to 45 characters
            cost = r.yesterday_cost
            cost_str = f"{cost:.2f}"
            delta_str = "N/A" if (r.delta_percentage is None) else f"{int(r.delta_percentage)}%"
            projects[project]["rows"].append((service, cost_str, delta_str))
            projects[project]["total_yesterday"] += cost
            projects[project]["total_day_before"] += (r.day_before_cost or 0)
            
            # Aggregated breakdown by SKU
            if service not in sku_agg:
                sku_agg[service] = {"yesterday": 0.0, "day_before": 0.0}
            sku_agg[service]["yesterday"] += cost
            sku_agg[service]["day_before"] += (r.day_before_cost or 0)
            
            # Totals by project
            if project not in project_totals:
                project_totals[project] = {"total_yesterday": 0.0, "total_day_before": 0.0}
            project_totals[project]["total_yesterday"] += cost
            project_totals[project]["total_day_before"] += (r.day_before_cost or 0)
        
        # --- Build Table 1: Aggregated breakdown by SKU (across all projects) ---
        sku_rows = []
        sorted_sku = sorted(sku_agg.items(), key=lambda item: item[1]["yesterday"], reverse=True)
        for sku, vals in sorted_sku:
            cost_str = f"{vals['yesterday']:.2f}"
            if vals['day_before'] > 0:
                delta = round((vals["yesterday"] - vals["day_before"]) / vals["day_before"] * 100)
                delta_str = f"{delta}%"
            else:
                delta_str = "N/A"
            sku_rows.append((sku, cost_str, delta_str))
        overall_sku_cost = f"{overall_total_yesterday:.2f}"
        if overall_total_day_before > 0:
            overall_sku_delta = round((overall_total_yesterday - overall_total_day_before) / overall_total_day_before * 100)
            overall_sku_delta_str = f"{overall_sku_delta}%"
        else:
            overall_sku_delta_str = "N/A"
        
        # Pass overall_label="OVERALL" so that the table ends with an OVERALL row
        sku_table_text = build_table(["SKU", "Cost", "Delta"], sku_rows, "OVERALL", overall_sku_cost, overall_sku_delta_str)
        
        # --- Build Table 2: Totals by project ---
        project_rows = []
        sorted_projects = sorted(project_totals.items(), key=lambda item: item[1]["total_yesterday"], reverse=True)
        for proj, totals in sorted_projects:
            cost_str = f"{totals['total_yesterday']:.2f}"
            if totals['total_day_before'] > 0:
                delta = round((totals["total_yesterday"] - totals["total_day_before"]) / totals["total_day_before"] * 100)
                delta_str = f"{delta}%"
            else:
                delta_str = "N/A"
            project_rows.append((proj, cost_str, delta_str))
        overall_proj_cost = f"{overall_total_yesterday:.2f}"
        if overall_total_day_before > 0:
            overall_proj_delta = round((overall_total_yesterday - overall_total_day_before) / overall_total_day_before * 100)
            overall_proj_delta_str = f"{overall_proj_delta}%"
        else:
            overall_proj_delta_str = "N/A"
        # Build the full project table, then remove the OVERALL row (last 2 lines)
        project_table_text_full = build_table(["Project", "Cost", "Delta"], project_rows, "OVERALL", overall_proj_cost, overall_proj_delta_str)
        project_table_text_lines = project_table_text_full.split("\n")
        if len(project_table_text_lines) >= 2:
            project_table_text = "\n".join(project_table_text_lines[:-2])
        else:
            project_table_text = project_table_text_full
        
        # --- Build Date Block ---
        date_block = {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Date:* {cost_date}"}
            ]
        }
        
        # --- Build Main Message (2 blocks) ---
        main_block1 = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n{sku_table_text}\n```"}
        }
        main_blocks = [date_block, main_block1]
        # If SEND_PROJECT_BREAKDOWN is enabled, add the second block with project totals
        if SEND_PROJECT_BREAKDOWN:
            main_block2 = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{project_table_text}\n```"}
            }
            main_blocks.append(main_block2)
        main_ts = send_slack_message(main_blocks)
        
        # --- Send Thread Messages for each project (detailed breakdown by SKU) ---
        if SEND_THREAD_DETAILS:
            # Sort projects by total cost (from highest to lowest)
            sorted_projects_by_cost = sorted(projects.items(), key=lambda item: item[1]["total_yesterday"], reverse=True)
            for proj, data in sorted_projects_by_cost:
                rows = data["rows"]
                total_yesterday = data["total_yesterday"]
                total_day_before = data["total_day_before"]
                if total_day_before > 0:
                    proj_delta = round((total_yesterday - total_day_before) / total_day_before * 100)
                    proj_delta_str = f"{proj_delta}%"
                else:
                    proj_delta_str = "N/A"
                # Sort rows within the project by cost descending
                proj_rows = sorted(rows, key=lambda r: float(r[1]), reverse=True)
                total_str = f"{total_yesterday:.2f}"
                proj_table_text = build_table(["SKU", "Cost", "Delta"], proj_rows, "TOTAL", total_str, proj_delta_str)
                
                # Build header block with project name
                thread_header_block = {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Project: {proj}", "emoji": True}
                }
                # Build table block
                thread_table_block = {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```\n{proj_table_text}\n```"}
                }
                # Send as thread message to the main message (main_ts)
                send_slack_message([thread_header_block, thread_table_block], thread_ts=main_ts)
        
        return "Success"
    except Exception as e:
        err_msg = f"Error executing BigQuery query: {e}"
        logging.error(err_msg)
        send_slack_message([{"type": "section", "text": {"type": "mrkdwn", "text": err_msg}}], fallback_text=err_msg)
        return "Error"

if __name__ == '__main__':
    print(get_gcp_cost(None))
