import os
import sys
import time
import random
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load environment variables from .env file
load_dotenv()

LOGIN_EMAIL = os.getenv("LOGIN_EMAIL", os.getenv("LINKEDIN_EMAIL"))
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", os.getenv("LINKEDIN_PASSWORD"))
TARGET_URL = os.getenv("TARGET_URL", "https://example.com/login")

# Jobs search configuration
JOBS_URL = os.getenv("JOBS_URL")
JOB_CARD_SELECTOR = os.getenv("JOB_CARD_SELECTOR", 'div[role="button"][componentkey^="job-card-component-ref-"], .job-listing-item, .job-card, li.jobs-search-results__list-item')
JOB_TITLE_SELECTOR = os.getenv("JOB_TITLE_SELECTOR", 'p[class*="_3e7ac687"] span[aria-hidden="true"], p._3e7ac687 span[aria-hidden="true"], .job-title')
JOB_COMPANY_SELECTOR = os.getenv("JOB_COMPANY_SELECTOR", 'p[class*="_77240ce7"], p._77240ce7, .company-name')

# Selector for the job description container inside the details pane
JOB_DESCRIPTION_SELECTOR = os.getenv(
    "JOB_DESCRIPTION_SELECTOR",
    '[componentkey^="JobDetails_AboutTheJob_"] [data-testid="expandable-text-box"], '
    '[id^="JobDetails_AboutTheJob_"] [data-testid="expandable-text-box"], '
    '.jobs-description__container, .jobs-box__html-content'
)

def validate_credentials():
    """Validates that credentials are set in the environment."""
    if not LOGIN_EMAIL or not LOGIN_PASSWORD:
        print("Error: LOGIN_EMAIL (or LINKEDIN_EMAIL) and LOGIN_PASSWORD (or LINKEDIN_PASSWORD) must be configured in your .env file.")
        print("Please copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

def get_paginated_url(url, start_val):
    """Safely updates or appends the 'start' query parameter in the target URL."""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    query_params["start"] = [str(start_val)]
    new_query = urlencode(query_params, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)

def find_element_with_fallback(page, selectors, name_for_logging):
    """Tries multiple locator strategies to find a visible element."""
    for selector in selectors:
        try:
            # Use the :visible modifier to target the active layout wrapper
            visible_selector = f"{selector}:visible"
            locator = page.locator(visible_selector).first
            locator.wait_for(state="visible", timeout=1000)
            print(f"Located {name_for_logging} using selector: '{visible_selector}'")
            return locator
        except Exception:
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=500)
                print(f"Located {name_for_logging} using selector: '{selector}'")
                return locator
            except Exception:
                continue
    return None

def type_like_human(locator, text):
    """Simulates a human typing by introducing randomized delays between keystrokes."""
    locator.click()
    # Clear any existing text
    locator.press("Control+A")
    locator.press("Backspace")
    
    # Type character-by-character with randomized pause speeds (between 60ms and 200ms)
    for char in text:
        locator.type(char)
        time.sleep(random.uniform(0.06, 0.20))

def simulate_human_pause(min_seconds=1.0, max_seconds=3.0):
    """Introduces a randomized delay to simulate human reaction/reading time."""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"Simulating human pause for {delay:.2f} seconds...")
    time.sleep(delay)

def login(page, email, password, target_url):
    """Handles the login process on the target URL."""
    # Use domcontentloaded to load pages faster and prevent hanging on external trackers
    print(f"Navigating to login page: {target_url}...")
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"Failed to navigate to target URL: {e}")
        return False
        
    email_selectors = [
        'input[autocomplete*="username"]',
        'input[type="email"]',
        'input[name="session_key"]',
        'input#username'
    ]
    
    password_selectors = [
        'input[autocomplete="current-password"]',
        'input[type="password"]',
        'input[name="session_password"]',
        'input#password'
    ]
    
    # Using exact regex text matching :text-matches(...) to avoid partial substring matching on Apple/Google sign-in buttons
    submit_selectors = [
        'button:text-matches("^Sign in$", "i")',
        '[role="button"]:text-matches("^Sign in$", "i")',
        'span:text-matches("^Sign in$", "i")',
        'button[type="submit"]',
        'button:text-is("Sign in")',
        'span:text-is("Sign in")',
        'input[type="submit"]'
    ]
    
    try:
        print("Waiting for login form to load...")
        # Wait for any of the visible email input elements to load
        combined_email_selector = ", ".join([f"{sel}:visible" for sel in email_selectors])
        page.wait_for_selector(combined_email_selector, state="visible", timeout=15000)
        
        # Form is loaded; now extract the elements using fallback logic
        username_field = find_element_with_fallback(page, email_selectors, "username field")
        password_field = find_element_with_fallback(page, password_selectors, "password field")
        submit_button = find_element_with_fallback(page, submit_selectors, "submit button")
        
        if not username_field or not password_field or not submit_button:
            raise PlaywrightTimeoutError("One or more key login elements could not be found.")
        
        # Simulate natural reading/thinking delay after the form loads
        simulate_human_pause(1.5, 3.5)
        
        # Enter credentials with human typing simulation
        print("Entering username...")
        type_like_human(username_field, email)
        
        simulate_human_pause(0.8, 2.0)
        
        print("Entering password...")
        type_like_human(password_field, password)
        
        simulate_human_pause(1.0, 2.5)
        
        # Submit the form
        print("Submitting login form...")
        submit_button.click()
        
        print("Waiting for page redirection/verification check...")
        time.sleep(3)
        
        current_url = page.url
        print(f"Current URL after login attempt: {current_url}")
        return True
    except Exception as e:
        print(f"An error occurred during login: {e}")
        return False

def fetch_jobs_and_descriptions(page, jobs_url, card_selector, title_selector, company_selector, description_selector, on_job_found=None, limit=None):
    """Navigates through paginated job search results and parses un-scraped jobs up to the specified limit."""
    # 1. Load already scraped job IDs from local database to skip duplicate scraping requests
    existing_job_ids = set()
    json_filename = "extracted_jobs.json"
    if os.path.exists(json_filename):
        try:
            with open(json_filename, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
                for job in existing_jobs:
                    job_id_val = job.get("jobId")
                    if job_id_val and job_id_val != "N/A":
                        existing_job_ids.add(job_id_val)
        except Exception as e:
            print(f"Warning: Could not read existing jobs for skipping: {e}")

    all_scraped_jobs = []
    
    # 2. Iterate pages start = 1, 26, 51, 76 to parse top 100 jobs
    for start_val in [1, 26, 51, 76]:
        if limit is not None and len(all_scraped_jobs) >= limit:
            break
            
        paginated_url = get_paginated_url(jobs_url, start_val)
        print(f"\n--- Navigating to paginated search page (start={start_val}) ---")
        simulate_human_pause(2.0, 4.0)
        
        try:
            page.goto(paginated_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Failed to navigate to jobs search URL (start={start_val}): {e}")
            continue
            
        print("Waiting for job listings to load...")
        try:
            # Wait for the card selector to render
            page.wait_for_selector(card_selector, state="visible", timeout=15000)
            
            # Fetch all matching job cards on this page
            job_cards = page.locator(card_selector).all()
            print(f"Found {len(job_cards)} job cards on this search page.")
            
            for index, card in enumerate(job_cards, start=1):
                if limit is not None and len(all_scraped_jobs) >= limit:
                    print(f"Reached requested limit of {limit} jobs. Stopping scraper.")
                    return all_scraped_jobs
                    
                try:
                    # Extract Job ID from componentkey
                    job_id = "N/A"
                    componentkey = card.get_attribute("componentkey")
                    if componentkey and "job-card-component-ref-" in componentkey:
                        job_id = componentkey.split("job-card-component-ref-")[-1]
                    
                    # Optimization: Skip already scraped jobs
                    if job_id != "N/A" and job_id in existing_job_ids:
                        print(f"Skipping already scraped job card {index} (jobId: {job_id})")
                        continue
                    
                    # Extract Title and Company Name
                    title_elem = card.locator(title_selector).first
                    company_elem = card.locator(company_selector).first
                    
                    title = title_elem.inner_text().strip() if title_elem.is_visible() else "N/A"
                    company = company_elem.inner_text().strip() if company_elem.is_visible() else "N/A"
                    
                    # Click the card to load details in the side panel
                    print(f"Clicking job card {index} (jobId: {job_id}): '{title}' | '{company}'...")
                    card.scroll_into_view_if_needed()
                    card.click()
                    
                    # Natural human-like pause to let the detail panel load
                    simulate_human_pause(1.5, 2.5)
                    
                    # Locate and extract the description
                    description_elem = page.locator(description_selector).first
                    description_elem.wait_for(state="visible", timeout=5000)
                    description = description_elem.inner_text().strip()
                    
                    # Print a snippet of the description
                    snippet = description[:150].replace('\n', ' ') + "..." if len(description) > 150 else description
                    print(f"Description Snippet: {snippet}")
                    
                    # Construct direct view URL as applying URL
                    applying_url = f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id != "N/A" else "N/A"
                    
                    # Collect structured data
                    job_data = {
                        "jobId": job_id,
                        "position_name": title,
                        "company_name": company,
                        "applying_url": applying_url,
                        "description": description
                    }
                    all_scraped_jobs.append(job_data)
                    
                    # Trigger real-time streaming callback if registered
                    if on_job_found:
                        try:
                            on_job_found(job_data)
                        except Exception as cb_err:
                            print(f"Error in on_job_found streaming callback: {cb_err}")
                    
                except Exception as e:
                    print(f"Error parsing job card #{index} on page start={start_val}: {e}")
        except PlaywrightTimeoutError:
            print(f"Timeout waiting for job listings ('{card_selector}') to appear on page start={start_val}.")
            continue
        except Exception as e:
            print(f"An error occurred while parsing jobs on page start={start_val}: {e}")
            continue
            
    print("--------------------------------------------\n")
    return all_scraped_jobs

def merge_and_save_jobs(new_jobs, json_filename="extracted_jobs.json"):
    """Merges newly scraped jobs with existing jobs to preserve verdicts/shouldApply keys using jobId."""
    existing_jobs = []
    if os.path.exists(json_filename):
        try:
            with open(json_filename, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read existing {json_filename}: {e}")
            
    # Key existing jobs by jobId
    jobs_dict = {}
    for job in existing_jobs:
        key = job.get("jobId")
        if key and key != "N/A":
            jobs_dict[key] = job
        
    # Merge new jobs
    new_added_count = 0
    for job in new_jobs:
        key = job.get("jobId")
        if not key or key == "N/A":
            continue
            
        if key not in jobs_dict:
            jobs_dict[key] = job
            new_added_count += 1
        else:
            # Update fields but preserve existing tags like shouldApply or reason
            for field in ["position_name", "company_name", "description", "applying_url"]:
                if field in job and job[field] != "N/A":
                    jobs_dict[key][field] = job[field]
                    
    merged_list = list(jobs_dict.values())
    
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, indent=4, ensure_ascii=False)
        
    print(f"Saved job listings to '{json_filename}'.")
    print(f"Scraped: {len(new_jobs)}, Added new: {new_added_count}, Total listings: {len(merged_list)}")

def perform_scraping(on_job_found=None, limit=None):
    """Entry point for modular login and fetching execution."""
    validate_credentials()
    
    print("Initializing Playwright Chromium Browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # 1. Login
        login_success = login(page, LOGIN_EMAIL, LOGIN_PASSWORD, TARGET_URL)
        
        # 2. Fetch jobs and save
        if login_success and JOBS_URL:
            scraped_jobs = fetch_jobs_and_descriptions(
                page, 
                JOBS_URL, 
                JOB_CARD_SELECTOR, 
                JOB_TITLE_SELECTOR, 
                JOB_COMPANY_SELECTOR, 
                JOB_DESCRIPTION_SELECTOR,
                on_job_found=on_job_found,
                limit=limit
            )
            merge_and_save_jobs(scraped_jobs)
        elif not JOBS_URL:
            print("No JOBS_URL configured in the environment. Skipping job search.")
        else:
            print("Login failed. Skipping jobs search stage.")
            
        if not os.getenv("RUN_BY_BOT"):
            print("\nScript execution finished. Browser remains open.")
            print("Press Enter in the terminal to close the browser and exit...")
            input()
        
        browser.close()

if __name__ == "__main__":
    try:
        perform_scraping()
    except KeyboardInterrupt:
        print("\nScript interrupted by user.")
