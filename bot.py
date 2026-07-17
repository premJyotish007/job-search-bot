import os
import sys
import json
import asyncio
import ssl
import atexit
import signal
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# ── Single-instance guard ──────────────────────────────────────────────────
# Prevents multiple bot processes from running simultaneously (which causes
# each Discord command to be handled by every instance, sending duplicate
# messages to the channel).
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")

def _check_existing_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # os.kill(pid, 0) checks existence without sending a signal
            os.kill(old_pid, 0)
            print(
                f"\u274c Another bot instance is already running (PID {old_pid}).\n"
                f"   Kill it first:  kill {old_pid}\n"
                f"   Or delete the lock file:  rm {PID_FILE}"
            )
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Stale PID file from a crashed/killed previous run — safe to overwrite
            print(f"[INFO] Removed stale PID file (previous bot exited uncleanly).")

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"[INFO] Bot started (PID {os.getpid()}). Lock file written.")

def _cleanup_pid_file():
    """Remove the PID lock file on any exit."""
    try:
        os.remove(PID_FILE)
        print("[INFO] PID lock file removed. Bot exiting cleanly.")
    except FileNotFoundError:
        pass

def _signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM gracefully."""
    print(f"\n[INFO] Received signal {signum}. Shutting down...")
    _cleanup_pid_file()
    sys.exit(0)

_check_existing_instance()
atexit.register(_cleanup_pid_file)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
# ──────────────────────────────────────────────────────────────────────────

# Bypasses local SSL certificate issues common in macOS Python installations
ssl._create_default_https_context = ssl._create_unverified_context

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RESUME_FILE = "experiences.txt"
JOBS_FILE = "extracted_jobs.json"

if not DISCORD_BOT_TOKEN:
    print("Error: DISCORD_BOT_TOKEN is not configured in your .env file.")
    sys.exit(1)

# Enable necessary intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Import scraper and analyzer helpers
try:
    from linkedin_scraping import perform_scraping
    from analyze import analyze_single_job, save_single_job_to_json
except ImportError as e:
    print(f"Error importing scraper/analyzer helpers: {e}")
    sys.exit(1)

class JobAppliedView(discord.ui.View):
    """A persistent view containing a toggle button representing the 'applied' checkbox status."""
    def __init__(self, job_id, is_applied):
        super().__init__(timeout=None)  # Indefinite timeout for view persistence
        self.job_id = job_id
        self.is_applied = is_applied
        
        style = discord.ButtonStyle.green if is_applied else discord.ButtonStyle.grey
        label = "Applied ✅" if is_applied else "Mark Applied"
        custom_id = f"toggle_applied:{job_id}"
        
        self.toggle_button = discord.ui.Button(
            label=label,
            style=style,
            custom_id=custom_id
        )
        self.toggle_button.callback = self.toggle_callback
        self.add_item(self.toggle_button)

    async def toggle_callback(self, interaction: discord.Interaction):
        if not os.path.exists(JOBS_FILE):
            await interaction.response.send_message("⚠️ Jobs database not found.", ephemeral=True)
            return
            
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                jobs = json.load(f)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Error reading database: {e}", ephemeral=True)
            return
            
        found = False
        new_applied_state = False
        for job in jobs:
            if job.get("jobId") == self.job_id:
                current_state = job.get("applied") == "true"
                new_state = not current_state
                job["applied"] = "true" if new_state else "false"
                new_applied_state = new_state
                found = True
                break
                
        if found:
            try:
                with open(JOBS_FILE, "w", encoding="utf-8") as f:
                    json.dump(jobs, f, indent=4, ensure_ascii=False)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ Error writing database: {e}", ephemeral=True)
                return
                
            print(f"[BUTTON LOG] Toggled applied state for job ID {self.job_id} to {new_applied_state}")
            
            # Update UI state dynamically
            self.is_applied = new_applied_state
            self.toggle_button.style = discord.ButtonStyle.green if new_applied_state else discord.ButtonStyle.grey
            self.toggle_button.label = "Applied ✅" if new_applied_state else "Mark Applied"
            
            # Edit the message on-the-fly to reflect check status
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("⚠️ Job not found in database.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot successfully logged in as {bot.user.name} ({bot.user.id})")
    print("Commands:")
    print("  !find [limit]    - Scrapes jobs from LinkedIn and streams listings as they are found.")
    print("  !analyze [limit] - Performs resume analysis on unassigned jobs and streams verdicts.")
    print("  !referral <comp> - Searches for connections working at specified company.")
    print("  !reachout        - Generates outreach template (reply to a connection card).")
    print("-------------------------------------------------------------")
    
    # Register persistent button views for existing jobs to survive bot restarts
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                jobs = json.load(f)
                for job in jobs:
                    jid = job.get("jobId")
                    if jid and jid != "N/A":
                        is_app = job.get("applied") == "true"
                        bot.add_view(JobAppliedView(jid, is_app))
            print("Successfully registered persistent button views for all existing jobs.")
        except Exception as e:
            print(f"Error registering persistent views: {e}")

@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author.bot:
        return

    # Keep fallback text reply listener "done" for convenience
    if message.reference and message.content.strip().lower() == "done":
        try:
            referenced_msg = message.reference.resolved
            if not isinstance(referenced_msg, discord.Message):
                referenced_msg = await message.channel.fetch_message(message.reference.message_id)
                
            job_id = None
            if referenced_msg.embeds:
                embed = referenced_msg.embeds[0]
                if embed.url:
                    url = embed.url
                    if "/view/" in url:
                        job_id = url.split("/view/")[-1].replace("/", "").split("?")[0]
                        
            if not job_id and referenced_msg.content:
                if "/view/" in referenced_msg.content:
                    job_id = referenced_msg.content.split("/view/")[-1].replace("/", "").split("?")[0]
                    
            if job_id:
                if os.path.exists(JOBS_FILE):
                    with open(JOBS_FILE, "r", encoding="utf-8") as f:
                        jobs = json.load(f)
                        
                    found = False
                    for job in jobs:
                        if job.get("jobId") == job_id:
                            job["applied"] = "true"
                            found = True
                            position = job.get("position_name", "Unknown Position")
                            company = job.get("company_name", "Unknown Company")
                            break
                            
                    if found:
                        with open(JOBS_FILE, "w", encoding="utf-8") as f:
                            json.dump(jobs, f, indent=4, ensure_ascii=False)
                        await message.reply(f"✅ Marked **{position}** at **{company}** as applied!")
                    else:
                        await message.reply(f"⚠️ Job ID `{job_id}` was parsed but not found in `{JOBS_FILE}`.")
                else:
                    await message.reply(f"⚠️ `{JOBS_FILE}` does not exist.")
            else:
                await message.reply("⚠️ Could not extract a valid Job ID from the replied message.")
        except Exception as e:
            await message.reply(f"⚠️ Error marking job as applied: {e}")

    await bot.process_commands(message)

@bot.command(name="find")
async def find_jobs(ctx, limit: int = None):
    """Triggers job scraping and streams job details with a check toggle button up to an optional limit."""
    limit_info = f" (up to {limit} jobs)" if limit is not None else ""
    await ctx.send(f"🚀 **Starting LinkedIn Job Scraper{limit_info}...** This launches Playwright browser automation. Streaming results in real-time...")
    
    os.environ["RUN_BY_BOT"] = "True"
    loop = asyncio.get_running_loop()
    
    def on_job_found(job_data):
        position = job_data.get("position_name", "N/A")
        company = job_data.get("company_name", "N/A")
        url = job_data.get("applying_url", "N/A")
        job_id = job_data.get("jobId", "N/A")
        
        print(f"[FIND LOG] Processed job card: '{position}' at '{company}' (ID: {job_id})")
        
        # Instantiate button view (initially false/unapplied)
        view = JobAppliedView(job_id, False)
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🔍 **Found Job Card:** '{position}' at '{company}'\n🔗 Link: {url}", view=view),
            loop
        )
        
    try:
        await asyncio.to_thread(perform_scraping, on_job_found=on_job_found, limit=limit)
        await ctx.send("🏁 **Scraper finished!** All listings on the page have been saved to local database. Run `!analyze` to start matching them against Shreya's resume.")
    except Exception as e:
        await ctx.send(f"⚠️ An error occurred during scraping execution: {e}")

@bot.command(name="analyze")
async def analyze_jobs_cmd(ctx, limit: int = None):
    """Runs Gemini analysis on unassigned, unapplied jobs (up to an optional limit) and streams all unapplied job cards in real-time."""
    if not os.path.exists(RESUME_FILE):
        await ctx.send(f"⚠️ Error: Resume file '{RESUME_FILE}' not found in the workspace.")
        return
        
    if not os.path.exists(JOBS_FILE):
        await ctx.send(f"⚠️ Error: Job listings file '{JOBS_FILE}' not found. Please run `!find` first.")
        return
        
    try:
        with open(RESUME_FILE, "r", encoding="utf-8") as f:
            resume_content = f.read()
    except Exception as e:
        await ctx.send(f"⚠️ Error reading resume file: {e}")
        return
        
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except Exception as e:
        await ctx.send(f"⚠️ Error reading job database: {e}")
        return
        
    # Filter out already applied jobs
    unapplied_jobs = [j for j in jobs if j.get("applied") != "true"]
    
    if not unapplied_jobs:
        await ctx.send("✅ No unapplied job listings found in the database. Run `!find` first.")
        return
        
    # Apply limit if specified
    if limit is not None:
        unapplied_jobs = unapplied_jobs[:limit]
        limit_info = f" (limited to {limit} jobs)"
    else:
        limit_info = ""
        
    await ctx.send(f"🤖 **Starting Gemini Resume Matcher...** Processing **{len(unapplied_jobs)}** unapplied jobs{limit_info} in real-time...")
    
    for idx, job in enumerate(unapplied_jobs, start=1):
        position = job.get("position_name", "N/A")
        company = job.get("company_name", "N/A")
        url = job.get("applying_url", "https://www.linkedin.com/jobs")
        job_id = job.get("jobId", "N/A")
        
        should_apply = job.get("shouldApply")
        reason = job.get("reason")
        
        # If the job lacks a stored verdict, run a fresh analysis
        if should_apply is None:
            status_msg = await ctx.send(f"⏳ [{idx}/{len(unapplied_jobs)}] Analyzing fit: '{position}' at '{company}'...")
            
            verdict = await asyncio.to_thread(analyze_single_job, job, resume_content)
            
            if not verdict:
                print(f"[ANALYZE LOG] Error analyzing job: '{position}' at '{company}'")
                await status_msg.edit(content=f"⚠️ [{idx}/{len(unapplied_jobs)}] Failed to analyze '{position}' at '{company}' due to API error.")
                continue
                
            should_apply = verdict.get("shouldApply", "false").lower()
            reason = verdict.get("reason", "No reason provided.")
            
            job["shouldApply"] = should_apply
            job["reason"] = reason
            
            save_single_job_to_json(job, JOBS_FILE)
            await status_msg.delete()
            
            # Delay to respect Gemini API rate limits
            rate_limit_delay = 2.0
        else:
            should_apply = should_apply.lower()
            rate_limit_delay = 0.5
            
        print(f"[ANALYZE LOG] Processed analysis for job: '{position}' at '{company}' (Verdict: {should_apply})")
        
        # Post the final job card with the view attached
        if should_apply == "true":
            # Build interactive toggle checkbox view
            is_applied_bool = job.get("applied") == "true"
            view = JobAppliedView(job_id, is_applied_bool)
            
            embed = discord.Embed(
                title=f"{idx}. 🎯 MATCH: {position}",
                description=reason,
                color=discord.Color.green(),
                url=url
            )
            embed.add_field(name="Company", value=company, inline=True)
            embed.add_field(name="Direct Link", value=f"[Apply on LinkedIn]({url})", inline=True)
            embed.set_footer(text=f"Card {idx}/{len(unapplied_jobs)} | gemini-3.1-flash-lite")
            await ctx.send(embed=embed, view=view)
        else:
            # Single-line message for rejected/skipped jobs
            await ctx.send(f"❌ SKIPPED: {url} because {reason}")
            
        await asyncio.sleep(rate_limit_delay)
        
    await ctx.send("🏁 **Gemini Analysis complete!** All unapplied job cards processed.")

@bot.command(name="referral")
async def referral_cmd(ctx, *, company: str):
    """Searches for connections working at the specified company and streams results."""
    await ctx.send(f"🔍 **Starting Referral Search for '{company}'...** Launching browser automation. Streaming connections...")
    
    os.environ["RUN_BY_BOT"] = "True"
    loop = asyncio.get_running_loop()
    
    def on_person_found(person_data):
        name = person_data.get("name", "Unknown Name")
        url = person_data.get("url", "https://www.linkedin.com")
        headline = person_data.get("headline", "No headline available")
        
        print(f"[REFERRAL LOG] Found connection: '{name}' | '{headline}' (URL: {url})")
        
        embed = discord.Embed(
            title=f"👤 Connection: {name}",
            description=headline,
            color=discord.Color.blue(),
            url=url
        )
        embed.add_field(name="LinkedIn Profile", value=f"[View Profile]({url})", inline=False)
        embed.set_footer(text=f"Company: {company} | Referral Finder")
        
        asyncio.run_coroutine_threadsafe(
            ctx.send(embed=embed),
            loop
        )
        
    try:
        from linkedin_scraping import perform_referral_search
        people = await asyncio.to_thread(perform_referral_search, company_name=company, on_person_found=on_person_found)
        await ctx.send(f"🏁 **Referral Search finished!** Found a total of **{len(people)}** connection(s).")
    except Exception as e:
        await ctx.send(f"⚠️ An error occurred during referral search execution: {e}")

@bot.command(name="reachout")
async def reachout_cmd(ctx, job_link: str = None):
    """Generates an outreach message template for a connection card (triggered by replying to a referral connection card)."""
    # Verify this is a reply
    if not ctx.message.reference or not ctx.message.reference.message_id:
        await ctx.reply("⚠️ This command can only be used as a reply to a connection card generated by the `!referral` command.")
        return
        
    try:
        referenced_msg = ctx.message.reference.resolved
        if not isinstance(referenced_msg, discord.Message):
            referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            
        # Verify it has embeds
        if not referenced_msg.embeds:
            await ctx.reply("⚠️ This command can only be used as a reply to a connection card generated by the `!referral` command.")
            return
            
        embed = referenced_msg.embeds[0]
        
        # Check if footer contains company name
        footer_text = embed.footer.text if embed.footer else ""
        if not footer_text or not footer_text.startswith("Company:"):
            await ctx.reply("⚠️ This command can only be used as a reply to a connection card generated by the `!referral` command.")
            return
            
        # Extract company name and person name
        company_name = footer_text.split(" | ")[0].replace("Company: ", "").strip()
        person_name = embed.title.replace("👤 Connection: ", "").strip()
        
        company_key = company_name.lower()
        json_filename = "companyData.json"
        
        # Load companyData.json
        data = {}
        if os.path.exists(json_filename):
            try:
                with open(json_filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error reading {json_filename}: {e}")
                
        # If company not in data, initialize it
        if company_key not in data or not isinstance(data[company_key], dict):
            data[company_key] = {"code": None, "template": None}
            
        template = data[company_key].get("template")
        
        # If template doesn't exist, generate via Gemini and save
        if not template:
            status_msg = await ctx.reply("🤖 **Generating personalized outreach template via Gemini...**")
            
            from analyze import generate_outreach_template
            ai_template = await asyncio.to_thread(generate_outreach_template, company_name=company_name)
            
            try:
                await status_msg.delete()
            except Exception:
                pass
                
            if ai_template:
                template = ai_template
            else:
                # Fallback to default template if API fails
                template = f"I'm reaching out today because I'm interested in working at company {company_name}."
                
            data[company_key]["template"] = template
            # Save updated companyData.json
            try:
                with open(json_filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving {json_filename}: {e}")
                
        # Strip any existing footer from the template if it exists
        if template:
            if "here's my resume for your review" in template.lower():
                parts = template.split("Here's my resume for your review")
                if len(parts) > 1:
                    template = parts[0].strip()
                else:
                    parts = template.split("here's my resume for your review")
                    if len(parts) > 1:
                        template = parts[0].strip()

        # Check if template has an existing salutation for compatibility
        template_lower = template.strip().lower() if template else ""
        if template_lower.startswith("hi ") or template_lower.startswith("hi,") or template_lower.startswith("hello"):
            personalized_message = template
            for placeholder in ["<name>", "[Name]", "[name]", "<Name>"]:
                personalized_message = personalized_message.replace(placeholder, person_name, 1)
        else:
            # Prepend "Hi <actual name>,"
            first_name = person_name.split()[0] if person_name else ""
            personalized_message = f"Hi {first_name},\n\n{template}"
        
        # Construct the dynamic footer
        job_line = f"This is the position I'm interested in: {job_link}\n" if job_link else ""
        footer = (
            f"\n\nHere's my resume for your review: https://drive.google.com/file/d/1QFG5M9nt4OizkJhQhxwk7zWHGRgh8Q88/view?usp=sharing.\n"
            f"{job_line}\n"
            f"Would you be open to referring my application?\n\n"
            f"Best,\n"
            f"Shreya"
        )
        
        # Append dynamic footer
        personalized_message = f"{personalized_message.strip()}{footer}"
        
        # Return the template message in Discord chat
        await ctx.reply(personalized_message)
        
    except Exception as e:
        await ctx.reply(f"⚠️ Error generating reachout message: {e}")

if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"Error starting Discord bot: {e}")
