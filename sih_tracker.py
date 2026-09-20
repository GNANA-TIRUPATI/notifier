import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright  # pyrefly: ignore

PS_ID = "SIH26187"
PORTAL_URL = "https://sih.gov.in/sih2026PS"

# Column headers matching the visible DataTable columns (0-indexed)
COLUMNS = [
    "S.No.",
    "Organization",
    "Problem Statement Title",
    "Category",
    "PS Number",
    "Submitted Idea(s) Count",
    "Theme",
    "Deadline for Idea Submission",
]


def fetch_submission_count():
  """Scrape the SIH portal DataTable for the target problem statement row."""
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
      page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")

      # Wait for the DataTable to render rows
      page.wait_for_selector(
          "#dataTablePS tbody tr td", timeout=45000, state="attached"
      )

      # Filter using the search box if present
      search_input = page.locator('input[type="search"]').first
      try:
        search_input.wait_for(state="attached", timeout=10000)
        search_input.fill(PS_ID)
        page.wait_for_timeout(1500)
      except Exception:
        pass

      # Locate the filtered row in the main DataTable
      target_row = page.locator(f"#dataTablePS tbody tr:has-text('{PS_ID}')")
      try:
        target_row.first.wait_for(state="attached", timeout=15000)
      except Exception:
        pass
      if target_row.count() == 0:
        # Capture diagnostic info on failure
        page_title = page.title()
        page.screenshot(path="debug_failure.png")
        all_text = page.locator("#dataTablePS").inner_text()[:500]
        browser.close()
        return None, (
            f"PS ID '{PS_ID}' not found after search. "
            f"Page title: '{page_title}'. "
            f"Table preview: {all_text}"
        )

      # Extract only the direct visible <td> cells from the first matching row
      # The SIH table embeds hidden modal content inside <td> elements, so we
      # use JavaScript to read only the 8 top-level <td> children directly
      row_handle = target_row.first.element_handle()
      cells_data = page.evaluate(
          """(row) => {
            const tds = row.querySelectorAll(':scope > td');
            return Array.from(tds).map((td, index) => {
              // For most columns, grab only the first visible text node
              // Skip any nested modal/popup content
              const cloned = td.cloneNode(true);
              // Remove hidden modal dialogs embedded in cells
              cloned.querySelectorAll('.modal, [style*="display: none"], .collapse, .modal-dialog').forEach(el => el.remove());
              return cloned.textContent.trim().replace(/\\s+/g, ' ');
            });
          }""",
          row_handle,
      )

      browser.close()

      if not cells_data:
        return None, "Row found but could not extract cell data."

      # Build a dict mapping column names to values
      result = {}
      for i, col in enumerate(COLUMNS):
        result[col] = cells_data[i] if i < len(cells_data) else "N/A"

      return result, None

    except Exception as e:
      try:
        page.screenshot(path="debug_error.png")
      except Exception:
        pass
      browser.close()
      return None, str(e)


def send_email(data, error=None):
  """Send an HTML email with extraction results or error details."""
  sender_email = os.environ.get("SENDER_EMAIL")
  sender_password = os.environ.get("SENDER_APP_PASSWORD")
  recipient_raw = os.environ.get("RECIPIENT_EMAIL", "")

  recipients = [e.strip() for e in recipient_raw.split(",") if e.strip()]
  if not recipients:
    print("⚠️  No recipients configured in RECIPIENT_EMAIL.")
    return

  msg = MIMEMultipart("alternative")
  msg["From"] = sender_email
  msg["To"] = ", ".join(recipients)

  current_time = datetime.now().strftime("%d %b %Y, %I:%M %p UTC")

  if error:
    msg["Subject"] = f"⚠️ [SIH Alert] Tracking Issue for {PS_ID}"
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
      <h3>SIH Tracker — Error Report</h3>
      <p><strong>Checked At:</strong> {current_time}</p>
      <p style="color: #c0392b;"><strong>Error:</strong> {error}</p>
      <p style="font-size: 12px; color: #888;">This is an automated alert from your SIH Tracker workflow.</p>
    </body>
    </html>
    """
  else:
    submitted = data.get("Submitted Idea(s) Count", "N/A")
    msg["Subject"] = f"📊 [SIH Update] {PS_ID} — {submitted} Submissions"

    rows_html = "".join(
        f"""<tr>
          <td style="padding: 10px 14px; border: 1px solid #e0e0e0; font-weight: 600; background: #f8f9fa; white-space: nowrap;">{col}</td>
          <td style="padding: 10px 14px; border: 1px solid #e0e0e0;">{val}</td>
        </tr>"""
        for col, val in data.items()
    )

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #222; line-height: 1.6;">
      <h2 style="color: #1a73e8; margin-bottom: 5px;">SIH Problem Statement Tracker</h2>
      <p style="margin-top: 0;"><strong>Checked At:</strong> {current_time}</p>

      <table style="border-collapse: collapse; width: 100%; max-width: 650px; margin-top: 10px;">
        {rows_html}
      </table>

      <p style="font-size: 12px; color: #888; margin-top: 20px;">
        Automated notification from
        <a href="https://github.com/GNANA-TIRUPATI/notifier">GNANA-TIRUPATI/notifier</a>.
      </p>
    </body>
    </html>
    """

  msg.attach(MIMEText(html, "html"))

  with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, recipients, msg.as_string())
  print(f"✅ Email sent to: {', '.join(recipients)}")


if __name__ == "__main__":
  print(f"🔍 Fetching data for {PS_ID} from {PORTAL_URL}...")
  data, err = fetch_submission_count()

  if err:
    print(f"❌ Error: {err}")
  else:
    print(f"✅ Data extracted successfully:")
    for col, val in data.items():
      print(f"   {col}: {val}")

  send_email(data, err)
  print("🏁 Tracking run finished.")