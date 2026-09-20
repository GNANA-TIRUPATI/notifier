import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

PS_ID = "SIH26187"
PORTAL_URL = "https://sih.gov.in/sih2026PS"


def fetch_submission_count():
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Navigate to SIH portal
    page.goto(PORTAL_URL, timeout=60000, wait_until="networkidle")

    # If there's a search box for DataTables, filter by PS ID
    search_input = page.query_selector(
        'input[type="search"], #problemStatementTable_filter input'
    )
    if search_input:
      search_input.fill(PS_ID)
      page.wait_for_timeout(2000)

    # Find the row containing SIH26187
    row = page.locator(f"tr:has-text('{PS_ID}')")

    if row.count() == 0:
      browser.close()
      return None, "PS ID not found on page"

    # In SIH tables, 'Submitted Idea(s) Count' is typically column index 4 or 5
    # Extract all cell texts in that row
    cells = row.first.locator("td").all_text_contents()
    browser.close()

    return cells, None


def send_email(cells_data, error=None):
  sender_email = os.environ["SENDER_EMAIL"]
  sender_password = os.environ[
      "SENDER_APP_PASSWORD"
  ]  # Gmail App Password (16 chars)
  recipient_email = os.environ["RECIPIENT_EMAIL"]

  msg = MIMEMultipart("alternative")
  msg["From"] = sender_email
  msg["To"] = recipient_email

  current_time = datetime.now().strftime("%d %b %Y, %I:%M %p")

  if error:
    msg["Subject"] = f"⚠️ [SIH Alert] Tracking Issue for {PS_ID}"
    html = f"<p>Could not extract submission count at {current_time}. Error: {error}</p>"
  else:
    # Build a clean summary table of the row data
    msg["Subject"] = f"📊 [SIH Update] Current Submissions for {PS_ID}"
    table_content = "".join([f"<td>{c.strip()}</td>" for c in cells_data])
    html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>SIH Submission Tracker</h2>
            <p><strong>Problem Statement:</strong> {PS_ID} (CCTV / Video Analytics - Border Surveillance)</p>
            <p><strong>Checked At:</strong> {current_time}</p>
            <table border="1" cellpadding="8" style="border-collapse: collapse; margin-top: 15px;">
                <tr style="background-color: #f2f2f2;">
                    <th>Organization</th>
                    <th>Title</th>
                    <th>Category</th>
                    <th>PS Code</th>
                    <th>Submitted Ideas</th>
                    <th>Theme</th>
                </tr>
                <tr>{table_content}</tr>
            </table>
        </body>
        </html>
        """

  msg.attach(MIMEText(html, "html"))

  with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, recipient_email, msg.as_string())


if __name__ == "__main__":
  data, err = fetch_submission_count()
  send_email(data, err)
  print("Tracking completed and update email sent.")