import os
import sys
import json
import asyncio
import ssl
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Bypasses local SSL certificate issues common in macOS Python installations
ssl._create_default_https_context = ssl._create_unverified_context

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RESUME_FILE = "shreya_resume.tex"
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
        
        # Build interactive toggle checkbox view
        is_applied_bool = job.get("applied") == "true"
        view = JobAppliedView(job_id, is_applied_bool)
        
        # Post the final job card with the view attached
        if should_apply == "true":
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
            # Single-line message for rejected/skipped jobs with the button view attached
            await ctx.send(f"❌ SKIPPED: {url} because {reason}", view=view)
            
        await asyncio.sleep(rate_limit_delay)
        
    await ctx.send("🏁 **Gemini Analysis complete!** All unapplied job cards processed.")

if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"Error starting Discord bot: {e}")
