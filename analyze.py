import os
import sys
import json
import time
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESUME_FILE = "experiences.txt"
JOBS_FILE = "extracted_jobs.json"
MODEL_NAME = os.getenv("GEMINI_MODEL")
if not MODEL_NAME:
    MODEL_NAME = "gemini-3.1-flash-lite"

def list_supported_models():
    """Lists the available models supporting generateContent for diagnostic purposes."""
    try:
        print("Supported models for your API key:")
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                print(f" - {m.name}")
    except Exception as e:
        print(f"Failed to query model list: {e}")

def save_single_job_to_json(job, json_filename="extracted_jobs.json"):
    """Merges a single analyzed job listing with existing listings in the database file."""
    existing_jobs = []
    if os.path.exists(json_filename):
        try:
            with open(json_filename, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
        except Exception:
            pass
            
    # Key existing jobs by jobId
    jobs_dict = {}
    for j in existing_jobs:
        key = j.get("jobId")
        if key and key != "N/A":
            jobs_dict[key] = j
            
    # Key current job
    key = job.get("jobId")
    if key and key != "N/A":
        if key in jobs_dict:
            jobs_dict[key].update(job)
        else:
            jobs_dict[key] = job
            
    merged_list = list(jobs_dict.values())
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, indent=4, ensure_ascii=False)

def analyze_single_job(job, resume_content):
    """Submits a single job listing to Gemini for compatibility analysis based on experiences."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not configured.")
        return None
        
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except Exception as e:
        print(f"Failed to initialize model '{MODEL_NAME}': {e}")
        return None
        
    system_instruction = (
        "You are an expert career advisor assisting Shreya with her job applications.\n"
        "Your task is to review a job posting description and Shreya's experiences context, and decide whether it is worth applying or not.\n"
        "Apply these CRITICAL criteria strictly:\n"
        "1. Experience requirement: The job must require less than 2 years of experience (freshers, 0-1 years, or 1 year are ideal. If it strictly requires 2+ years, set shouldApply to 'false').\n"
        "2. Company size & reputation: The company must be reputable, with at least 1,000 employees.\n"
        "3. Fit check: Shreya's skills and accomplishments listed in her experiences must have reasonable alignment with the job description.\n\n"
        "You must respond in JSON format matching this EXACT schema:\n"
        "{\n"
        '  "shouldApply": "true" or "false" (must be string values),\n'
        '  "reason": "a one-liner reason for the verdict"\n'
        "}"
    )
    
    prompt = (
        f"--- CRITERIA ---\n"
        f"1. Less than 2 years experience requirement.\n"
        f"2. Reputable company with at least 1000 employees.\n\n"
        f"--- SHREYA'S EXPERIENCES ---\n"
        f"{resume_content}\n\n"
        f"--- JOB DETAILS ---\n"
        f"Position: {job.get('position_name')}\n"
        f"Company: {job.get('company_name')}\n"
        f"URL: {job.get('applying_url')}\n"
        f"Description:\n{job.get('description')}\n"
    )
    
    try:
        response = model.generate_content(
            contents=[system_instruction, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"Error calling Gemini for job '{job.get('position_name')}': {e}")
        return None

def analyze_jobs():
    """Reads job descriptions and Shreya's resume, filters them using Gemini API natively, and updates the dataset."""
    global MODEL_NAME
    
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY is not configured in your .env file.")
        sys.exit(1)
        
    if not os.path.exists(RESUME_FILE):
        print(f"Error: Resume file '{RESUME_FILE}' not found in the workspace.")
        sys.exit(1)
        
    if not os.path.exists(JOBS_FILE):
        print(f"Error: Job listings file '{JOBS_FILE}' not found. Run the scraper first.")
        sys.exit(1)
        
    # Read Resume
    print(f"Loading resume from '{RESUME_FILE}'...")
    with open(RESUME_FILE, "r", encoding="utf-8") as f:
        resume_content = f.read()
        
    # Read Jobs
    print(f"Loading job listings from '{JOBS_FILE}'...")
    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)
        
    # Filter jobs without a verdict
    unassigned_jobs = [job for job in jobs if "shouldApply" not in job]
    print(f"Total jobs: {len(jobs)}. Jobs needing analysis: {len(unassigned_jobs)}.")
    
    if not unassigned_jobs:
        print("No new jobs to analyze. All listings already have a verdict.")
        return
        
    # Configure Gemini API
    genai.configure(api_key=GEMINI_API_KEY)
    
    print(f"Initializing Gemini model '{MODEL_NAME}'...")
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except Exception as e:
        print(f"Failed to initialize model '{MODEL_NAME}': {e}")
        sys.exit(1)
        
    print(f"Starting analysis natively with model '{MODEL_NAME}'...")
    
    success_count = 0
    for idx, job in enumerate(jobs):
        if "shouldApply" in job:
            continue
            
        print(f"\nAnalyzing Job: '{job.get('position_name')}' at '{job.get('company_name')}'...")
        verdict = analyze_single_job(job, resume_content)
        
        if verdict:
            should_apply = verdict.get("shouldApply", "false").lower()
            reason = verdict.get("reason", "No reason provided.")
            
            job["shouldApply"] = should_apply
            job["reason"] = reason
            
            print(f"-> Verdict: shouldApply={should_apply} | Reason: {reason}")
            success_count += 1
            
            # Save incrementally
            save_single_job_to_json(job, JOBS_FILE)
            time.sleep(2.0)
            
    print(f"\nAnalysis complete. Successfully analyzed {success_count} jobs.")

def generate_outreach_template(company_name):
    """Generates a professional outreach template for a specific company using Gemini."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY is not configured.")
        return None
        
    # Read experiences
    experiences_file = "experiences.txt"
    try:
        with open(experiences_file, "r", encoding="utf-8") as f:
            experiences_content = f.read()
    except Exception as e:
        print(f"Error reading experiences file in outreach generator: {e}")
        experiences_content = ""

    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except Exception as e:
        print(f"Failed to initialize model '{MODEL_NAME}': {e}")
        return None
        
    prompt = f"""
You are writing a professional, personalized referral request outreach message template.

Here is the context:
- Applicant's Name: Shreya
- Target Company: {company_name}
- Applicant's Experiences:
{experiences_content}

Instructions:
1. Based on the real work experience, skills, and background documented in the provided Applicant's Experiences, come up with a highly tailored and relevant outreach message. Do NOT try to access or fetch any external links.
2. The message must strictly adhere to the following format structure:

Format/Guidelines:
1. Do NOT include any greeting or salutation (like 'Hi <name>,', 'Hi,', 'Hello', etc.) at the beginning. Start writing directly from the first paragraph of the body.

2. The first paragraph must talk briefly about the target company ({company_name}) and the applicant's intent to work there (e.g. why the company's engineering/work inspires them, and that they are applying for a software engineering/backend role).
3. The following paragraph must briefly highlight 2-3 key accomplishments from the provided Applicant's Experiences that directly align with engineering challenges at {company_name}. Make it highly specific to the actual background found on the experiences. Keep it concise and professional.
4. The ENTIRE generated text (excluding any salutation, since none should be generated) MUST be strictly less than or equal to 100 words. Do not let it exceed this limit under any circumstances.

Do not output any introductory or concluding remarks, explanations, markdown code blocks, or markdown formatting (like ```). Output ONLY the final message template.
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Strip any accidental markdown formatting
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text
    except Exception as e:
        print(f"Error generating outreach template with Gemini: {e}")
        return None

if __name__ == "__main__":
    analyze_jobs()
