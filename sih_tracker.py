import os
import smtplib
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# Ensure UTF-8 output on all platforms
if hasattr(sys.stdout, "reconfigure"):
  sys.stdout.reconfigure(encoding="utf-8")

PS_ID = "SIH26187"
PORTAL_URL = "https://sih.gov.in/sih2026PS"

# India Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

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

# Shared browser-like headers
HEADERS = {
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
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def parse_sih_html(html_text, target_ps_id=PS_ID):
  """Parse portal HTML and extract problem statement details."""
  soup = BeautifulSoup(html_text, "html.parser")
  table = soup.find("table", id="dataTablePS")
  if not table:
    return None, "Table #dataTablePS not found in portal HTML"

  tbody = table.find("tbody")
  if not tbody:
    return None, "tbody not found in #dataTablePS"

  rows = tbody.find_all("tr")
  print(f"    Found {len(rows)} rows in #dataTablePS")

  for tr in rows:
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


def fetch_with_requests():
  """Strategy 1: Use the requests library with session and retry logic."""
  try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
  except ImportError:
    return None, "requests library not installed"

  print("  [→] Trying requests library...")
  try:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)

    resp = session.get(PORTAL_URL, timeout=90, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    print(f"    Response: {resp.status_code}, size: {len(html)} bytes")

    if "dataTablePS" in html:
      data, err = parse_sih_html(html)
      if data:
        print("  [✓] Successfully extracted via requests")
        return data, None
      else:
        print(f"    [!] Table found but parse failed: {err}")
        return None, err
    else:
      print("    [!] dataTablePS not found in response HTML")
      return None, "dataTablePS not in response"
  except Exception as e:
    print(f"  [✗] requests failed: {e}")
    return None, str(e)


def fetch_with_curl():
  """Strategy 2: curl with browser headers and retries."""
  print("  [→] Trying curl...")
  try:
    cmd = [
        "curl",
        "-sS",
        "-L",
        "--max-time", "90",
        "--retry", "3",
        "--retry-delay", "5",
        "--compressed",
        "-H", f"User-Agent: {HEADERS['User-Agent']}",
        "-H", f"Accept: {HEADERS['Accept']}",
        "-H", f"Accept-Language: {HEADERS['Accept-Language']}",
        "-H", f"Referer: {HEADERS['Referer']}",
        "-H", "Connection: keep-alive",
        "-H", "Upgrade-Insecure-Requests: 1",
        PORTAL_URL,
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    if res.returncode == 0 and res.stdout:
      html = res.stdout.decode("utf-8", errors="replace")
      print(f"    Response size: {len(html)} bytes")
      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via curl")
          return data, None
        else:
          print(f"    [!] Table found but parse failed: {err}")
          return None, err
      else:
        print("    [!] dataTablePS not found in curl response")
        return None, "dataTablePS not in curl response"
    else:
      stderr_msg = res.stderr.decode("utf-8", errors="replace")[:200] if res.stderr else "no stderr"
      print(f"    [!] curl returned code {res.returncode}: {stderr_msg}")
      return None, f"curl exit code {res.returncode}"
  except FileNotFoundError:
    print("  [✗] curl not found on this system")
    return None, "curl not available"
  except Exception as e:
    print(f"  [✗] curl failed: {e}")
    return None, str(e)


def fetch_with_urllib():
  """Strategy 3: Python standard urllib."""
  print("  [→] Trying urllib...")
  try:
    req = urllib.request.Request(PORTAL_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as resp:
      html = resp.read().decode("utf-8", errors="replace")
      print(f"    Response size: {len(html)} bytes")
      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via urllib")
          return data, None
        else:
          print(f"    [!] Table found but parse failed: {err}")
          return None, err
      else:
        print("    [!] dataTablePS not found in urllib response")
        return None, "dataTablePS not in urllib response"
  except Exception as e:
    print(f"  [✗] urllib failed: {e}")
    return None, str(e)


def fetch_with_playwright():
  """Strategy 4: Playwright headless browser with stealth and explicit waits."""
  print("  [→] Trying Playwright headless browser...")
  try:
    from playwright.sync_api import sync_playwright  # pyrefly: ignore

    with sync_playwright() as p:
      browser = p.chromium.launch(
          headless=True,
          args=[
              "--disable-blink-features=AutomationControlled",
              "--no-sandbox",
              "--disable-setuid-sandbox",
              "--disable-dev-shm-usage",
          ],
      )
      context = browser.new_context(
          user_agent=HEADERS["User-Agent"],
          viewport={"width": 1920, "height": 1080},
          extra_http_headers={
              "Accept-Language": HEADERS["Accept-Language"],
              "Upgrade-Insecure-Requests": "1",
          },
      )
      page = context.new_page()

      # Inject stealth script to evade bot detection
      page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };
      """)

      page.goto(PORTAL_URL, timeout=90000, wait_until="networkidle")
      # Wait explicitly for the data table to appear
      page.wait_for_selector("#dataTablePS", timeout=30000)

      html = page.content()
      print(f"    Page content size: {len(html)} bytes")
      browser.close()

      if "dataTablePS" in html:
        data, err = parse_sih_html(html)
        if data:
          print("  [✓] Successfully extracted via Playwright")
          return data, None
        else:
          print(f"    [!] Table found but parse failed: {err}")
          return None, err
      else:
        print("    [!] dataTablePS not found in Playwright page")
        return None, "dataTablePS not in Playwright page"
  except Exception as e:
    print(f"  [✗] Playwright failed: {e}")
    return None, str(e)


def fetch_submission_count():
  """Fetch problem statement data using multi-strategy HTTP/browser fallback."""
  strategies = [
      ("requests", fetch_with_requests),
      ("curl", fetch_with_curl),
      ("urllib", fetch_with_urllib),
      ("playwright", fetch_with_playwright),
  ]

  errors = []
  for name, strategy_fn in strategies:
    data, err = strategy_fn()
    if data:
      return data, None
    if err:
      errors.append(f"{name}: {err}")

  error_summary = "; ".join(errors)
  return None, f"All fetch strategies failed for {PS_ID}. Details: {error_summary}"


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

  # Use IST (India Standard Time) for the timestamp
  current_time = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")

  if error:
    msg["Subject"] = f"⚠️ [SIH Alert] Tracking Issue for {PS_ID}"
    html = f"""\
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

    html = f"""\
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
  print(f"   Current time (IST): {datetime.now(IST).strftime('%d %b %Y, %I:%M %p IST')}")
  data, err = fetch_submission_count()

  if err:
    print(f"❌ Error: {err}")
  else:
    print("✅ Data extracted successfully:")
    for col, val in data.items():
      print(f"   {col}: {val}")

  send_email(data, err)
  print("🏁 Tracking run finished.")