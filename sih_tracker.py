from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib
from playwright.sync_api import sync_playwright  # pyrefly: ignore

SEARCH_QUERY = "AI-Based Intelligent Video Analytics Platform for Border Surveillance using existing CCTV Infrastructure"
PORTAL_URL = "https://sih.gov.in/sih2026PS"


def fetch_submission_count():
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    )
    page = context.new_page()

    try:
      page.goto(PORTAL_URL, timeout=90000, wait_until="networkidle")

      # Wait for DataTable to load
      page.wait_for_selector(
          "table tbody tr", timeout=45000, state="attached"
      )

      # Locate the search filter input
      search_input = page.locator(
          'input[type="search"], #problemStatementTable_filter input,'
          " .dataTables_filter input"
      ).first

      if search_input.is_visible():
        search_input.click()
        search_input.fill(SEARCH_QUERY)
        # Allow DataTables time to debounce and filter rows
        page.wait_for_timeout(3500)

      # Match the filtered row containing the title
      target_row = page.locator(
          "table tbody tr",
          has_text=(
              "AI-Based Intelligent Video Analytics Platform for Border"
              " Surveillance"
          ),
      )

      if target_row.count() == 0:
        browser.close()
        return None, f"No row found matching title after search filter."

      cells = target_row.first.locator("td").all_text_contents()
      browser.close()

      cleaned_cells = [c.strip().replace("\n", " ") for c in cells if c.strip()]
      return cleaned_cells, None

    except Exception as e:
      browser.close()
      return None, str(e)


def send_email(cells_data, error=None):
  sender_email = os.environ.get("SENDER_EMAIL")
  sender_password = os.environ.get("SENDER_APP_PASSWORD")
  recipient_raw = os.environ.get("RECIPIENT_EMAIL", "")

  recipients = [e.strip() for e in recipient_raw.split(",") if e.strip()]
  if not recipients:
    print("No recipients configured.")
    return

  msg = MIMEMultipart("alternative")
  msg["From"] = sender_email
  msg["To"] = ", ".join(recipients)

  current_time = datetime.now().strftime("%d %b %Y, %I:%M %p")

  if error:
    msg["Subject"] = "⚠️ [SIH Alert] Tracking Issue for CCTV PS"
    html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h3>SIH Tracker Notification</h3>
            <p><strong>Status:</strong> Could not retrieve count at {current_time} UTC.</p>
            <p style="color: #c0392b;"><strong>Details:</strong> {error}</p>
        </body>
        </html>
        """
  else:
    msg["Subject"] = "📊 [SIH Update] Current Submissions for Border CCTV PS"
    cells_markup = "".join(
        [
            (
                f"<td style='padding: 8px 12px; border: 1px solid #ddd;"
                f" font-size: 14px;'>{cell}</td>"
            )
            for cell in cells_data
        ]
    )

    html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222;">
            <h3 style="color: #1a73e8;">SIH Problem Statement Update</h3>
            <p><strong>Searched:</strong> {SEARCH_QUERY}</p>
            <p><strong>Checked At:</strong> {current_time} UTC</p>
            
            <table style="border-collapse: collapse; width: 100%; margin-top: 15px;">
                <thead>
                    <tr style="background-color: #f1f3f4; text-align: left;">
                        <th colspan="{len(cells_data)}" style="padding: 10px; border: 1px solid #ddd;">Matched Row Data</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>{cells_markup}</tr>
                </tbody>
            </table>
        </body>
        </html>
        """

  msg.attach(MIMEText(html, "html"))

  with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, recipients, msg.as_string())


if __name__ == "__main__":
  data, err = fetch_submission_count()
  send_email(data, err)
  print("Tracking run finished.")