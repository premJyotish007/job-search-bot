# LinkedIn Login Automation Tooling

A simple Python script using Selenium WebDriver to automate logging into LinkedIn using credentials configured in a `.env` file.

## Requirements

- Python 3.6 or higher
- Google Chrome installed

## Setup Instructions

1. **Install Dependencies**
   Run the following command to install the required libraries:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**
   Copy `.env.example` to `.env` and fill in your LinkedIn credentials:
   ```bash
   cp .env.example .env
   ```
   Open `.env` in a text editor and update:
   ```env
   LINKEDIN_EMAIL=your_email@example.com
   LINKEDIN_PASSWORD=your_password_here
   ```

3. **Run the Script**
   Run the main script using:
   ```bash
   python login_script.py
   ```

## Note on Security & Challenges
- The script initializes Google Chrome with the `detach` option enabled. This keeps the browser window open after execution finishes.
- If LinkedIn detects the automated browser and triggers a CAPTCHA or Verification Challenge, simply solve it manually inside the opened Chrome browser window.
