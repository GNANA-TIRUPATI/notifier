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
HOME_URL = "https://sih.gov.in/"

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


def fetch_with_playwright():
  """Strategy 1 (Primary): Playwright headless browser with WAF bypass.

  This is the primary strategy because the SIH portal uses Cloudflare/WAF
  that blocks datacenter IPs (like GitHub Actions). Playwright can handle
  WAF challenges by first visiting the homepage to get cookies, then
  navigating to the PS page.
  """
  print("  [→] Trying Playwright headless browser...")
  try:
    from playwright.sync_api import sync_playwright  # pyrefly: ignore
    import time

    with sync_playwright() as p:
      browser = p.chromium.launch(
          headless=True,
          args=[
              "--disable-blink-features=AutomationControlled",
              "--no-sandbox",
              "--disable-setuid-sandbox",
              "--disable-dev-shm-usage",
              "--disable-gpu",
              "--window-size=1920,1080",
          ],
      )
      context = browser.new_context(
          user_agent=HEADERS["User-Agent"],
          viewport={"width": 1920, "height": 1080},
          extra_http_headers={
              "Accept-Language": HEADERS["Accept-Language"],
              "Upgrade-Insecure-Requests": "1",
          },
          java_script_enabled=True,
      )
      page = context.new_page()

      # Inject stealth script to evade bot detection
      page.add_init_script("""
        // Override webdriver detection
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // Override plugins
        Object.defineProperty(navigator, 'plugins', {
          get: () => [1, 2, 3, 4, 5]
        });
        // Override languages
        Object.defineProperty(navigator, 'languages', {
          get: () => ['en-US', 'en']
        });
        // Override Chrome runtime
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
          parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
      """)

      # Step 1: Visit homepage first to get cookies and pass WAF challenge
      print("    Step 1: Visiting homepage to obtain cookies...")
      page.goto(HOME_URL, timeout=60000, wait_until="networkidle")
      # Wait for potential WAF challenge to resolve
      time.sleep(5)
      print(f"    Homepage loaded, URL: {page.url}")

      # Step 2: Navigate to the PS page (now with valid cookies)
      print("    Step 2: Navigating to problem statements page...")
      page.goto(PORTAL_URL, timeout=90000, wait_until="networkidle")

      # Step 3: Wait for the data table to appear with extended timeout
      print("    Step 3: Waiting for #dataTablePS table...")
      try:
        page.wait_for_selector("#dataTablePS", timeout=60000)
        print("    Table selector found!")
      except Exception:
        print("    Table selector timeout, checking for tbody rows...")
        try:
          page.wait_for_selector("#dataTablePS tbody tr", timeout=30000)
          print("    Table rows found!")
        except Exception:
          print("    No table rows found either, trying page content anyway...")

      # Step 4: Use the DataTable search box to filter for our PS ID
      # This is critical because the DataTable paginates (max 100 per page)
      # and PS IDs beyond the first page won't be in the DOM
      print(f"    Step 4: Searching for {PS_ID} in DataTable search box...")
      try:
        search_input = page.query_selector(
            'input[type="search"], input[aria-controls="dataTablePS"], '
            '#dataTablePS_filter input'
        )
        if search_input:
          search_input.fill(PS_ID)
          # Trigger DataTable search via events
          page.evaluate("""
            const input = document.querySelector('input[type="search"], input[aria-controls="dataTablePS"]');
            if (input) {
              input.dispatchEvent(new Event('input', { bubbles: true }));
              input.dispatchEvent(new Event('keyup', { bubbles: true }));
            }
            // Also try jQuery DataTables API if available
            if (window.jQuery && window.jQuery.fn.dataTable) {
              try { window.jQuery('#dataTablePS').DataTable().search('%s').draw(); } catch(e) {}
            }
          """ % PS_ID)
          # Wait for table to re-render with filtered results
          time.sleep(3)
          print(f"    Search filter applied for '{PS_ID}'")
        else:
          print("    [!] Search input not found, using raw page content")
      except Exception as e:
        print(f"    [!] Search filter failed: {e}, using raw page content")

      html = page.content()
      page_url = page.url
      print(f"    Final URL: {page_url}")
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
        # Check what we got instead
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else "No title"
        print(f"    [!] dataTablePS not found. Page title: '{title_text}'")
        # Check if it's a Cloudflare challenge page
        if "challenge" in html.lower() or "cloudflare" in html.lower() or "cf-" in html.lower():
          print("    [!] Detected Cloudflare/WAF challenge page")
          return None, "WAF challenge page detected, could not bypass"
        return None, f"dataTablePS not in Playwright page (title: {title_text})"
  except ImportError:
    print("  [✗] Playwright not installed")
    return None, "playwright not installed"
  except Exception as e:
    print(f"  [✗] Playwright failed: {e}")
    return None, str(e)


def fetch_with_requests():
  """Strategy 2: Use the requests library with session, cookies, and retry logic."""
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

    # Step 1: Visit homepage first to get cookies (WAF bypass)
    print("    Visiting homepage first for cookies...")
    home_resp = session.get(HOME_URL, timeout=60, allow_redirects=True)
    print(f"    Homepage: {home_resp.status_code}, cookies: {len(session.cookies)}")

    # Step 2: Now fetch the PS page with cookies
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
  """Strategy 3: curl with browser headers, cookie jar, and retries."""
  print("  [→] Trying curl...")
  try:
    import tempfile
    cookie_jar = os.path.join(tempfile.gettempdir(), "sih_cookies.txt")

    # Step 1: Visit homepage to get cookies
    print("    Visiting homepage first for cookies...")
    home_cmd = [
        "curl", "-sS", "-L",
        "--max-time", "60",
        "--compressed",
        "-c", cookie_jar,
        "-H", f"User-Agent: {HEADERS['User-Agent']}",
        "-H", f"Accept: {HEADERS['Accept']}",
        "-H", f"Referer: {HEADERS['Referer']}",
        "-H", "Connection: keep-alive",
        "-H", "Upgrade-Insecure-Requests: 1",
        "-o", "/dev/null",
        HOME_URL,
    ]
    subprocess.run(home_cmd, capture_output=True, timeout=75)

    # Step 2: Fetch the PS page with cookies
    cmd = [
        "curl", "-sS", "-L",
        "--max-time", "90",
        "--retry", "3",
        "--retry-delay", "5",
        "--compressed",
        "-b", cookie_jar,
        "-c", cookie_jar,
        "-H", f"User-Agent: {HEADERS['User-Agent']}",
        "-H", f"Accept: {HEADERS['Accept']}",
        "-H", f"Accept-Language: {HEADERS['Accept-Language']}",
        "-H", f"Referer: {HEADERS['Referer']}",
        "-H", "Connection: keep-alive",
        "-H", "Upgrade-Insecure-Requests: 1",
        PORTAL_URL,
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=120)

    # Clean up cookie jar
    try:
      os.remove(cookie_jar)
    except OSError:
      pass

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
  """Strategy 4: Python standard urllib with cookie handling."""
  print("  [→] Trying urllib...")
  try:
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # Step 1: Visit homepage to get cookies
    print("    Visiting homepage first for cookies...")
    home_req = urllib.request.Request(HOME_URL, headers=HEADERS)
    opener.open(home_req, timeout=60)
    print(f"    Homepage cookies: {len(cj)}")

    # Step 2: Fetch the PS page with cookies
    req = urllib.request.Request(PORTAL_URL, headers=HEADERS)
    with opener.open(req, timeout=90) as resp:
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


def fetch_submission_count():
  """Fetch problem statement data using multi-strategy HTTP/browser fallback.

  Strategy order:
  1. Playwright (best for WAF bypass - runs real browser)
  2. requests (session with cookies)
  3. curl (cookie jar)
  4. urllib (cookie processor)
  """
  strategies = [
      ("playwright", fetch_with_playwright),
      ("requests", fetch_with_requests),
      ("curl", fetch_with_curl),
      ("urllib", fetch_with_urllib),
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