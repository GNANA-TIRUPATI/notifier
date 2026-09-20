import os
import smtplib
import subprocess
import sys
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# Ensure UTF-8 output on all platforms
if hasattr(sys.stdout, "reconfigure"):
  sys.stdout.reconfigure(encoding="utf-8")

PS_ID = "SIH26187"
PORTAL_URL = "https://sih.gov.in/sih2026PS"

# Visible DataTable columns
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


def parse_sih_html(html_text, target_ps_id=PS_ID):
  """Parse portal HTML and extract problem statement details."""
  soup = BeautifulSoup(html_text, "html.parser")
  table = soup.find("table", id="dataTablePS")
  if not table:
    return None, "Table #dataTablePS not found in portal HTML"

  tbody = table.find("tbody")
  if not tbody:
    return None, "tbody not found in #dataTablePS"

  for tr in tbody.find_all("tr"):
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 8:
      continue
    ps_number = tds[4].get_text(strip=True)
    if ps_number == target_ps_id:
      title_cell = tds[2]
      link = title_cell.find("a")
      title = (
          link.get_text(strip=True) if link else title_cell.get_text(strip=True)
      )
      return {
          "S.No.": tds[0].get_text(strip=True),
          "Organization": tds[1].get_text(strip=True),
          "Problem Statement Title": title,
          "Category": tds[3].get_text(strip=True),
          "PS Number": ps_number,
          "Submitted Idea(s) Count": tds[5].get_text(strip=True),
          "Theme": tds[6].get_text(strip=True),
          "Deadline for Idea Submission": tds[7].get_text(strip=True),
      }, None

  return None, f"PS ID '{target_ps_id}' not found in table rows"


def fetch_submission_count():
  """Fetch problem statement data using multi-strategy HTTP/browser fallback."""
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/126.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,"
          "image/avif,image/webp,*/*;q=0.8"
      ),
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": "https://sih.gov.in/",
  }

  # Strategy 1: curl with browser headers (optimal on Linux CI runners against WAF)
  try:
    cmd = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        "60",
        "--compressed",
        "-H",
        f"User-Agent: {headers['User-Agent']}",
        "-H",
        f"Accept: {headers['Accept']}",
        "-H",
        f"Accept-Language: {headers['Accept-Language']}",
        "-H",
        f"Referer: {headers['Referer']}",
        PORTAL_URL,
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=75)
    if res.returncode == 0 and len(res.stdout) > 50000:
      html = res.stdout.decode("utf-8", errors="replace")
      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via curl")
          return data, None
  except Exception as e:
    print(f"  [i] curl attempt skipped: {e}")

  # Strategy 2: Python standard urllib
  try:
    req = urllib.request.Request(PORTAL_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
      html = resp.read().decode("utf-8", errors="replace")
      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via urllib")
          return data, None
  except Exception as e:
    print(f"  [i] urllib attempt skipped: {e}")

  # Strategy 3: Playwright headless browser fallback
  try:
    from playwright.sync_api import sync_playwright  # pyrefly: ignore

    with sync_playwright() as p:
      browser = p.chromium.launch(
          headless=True,
          args=[
              "--disable-blink-features=AutomationControlled",
              "--no-sandbox",
              "--disable-setuid-sandbox",
          ],
      )
      context = browser.new_context(
          user_agent=headers["User-Agent"],
          viewport={"width": 1920, "height": 1080},
          extra_http_headers=headers,
      )
      page = context.new_page()
      page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")
      html = page.content()
      browser.close()
      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via Playwright")
          return data, None
  except Exception as e:
    print(f"  [i] playwright fallback skipped: {e}")

  return None, f"All fetch strategies failed to retrieve table data for {PS_ID}."


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
    print("✅ Data extracted successfully:")
    for col, val in data.items():
      print(f"   {col}: {val}")

  send_email(data, err)
  print("🏁 Tracking run finished.")