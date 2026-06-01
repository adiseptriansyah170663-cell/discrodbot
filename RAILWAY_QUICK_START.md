RAILWAY DISCORD BOT - QUICK START CHECKLIST
===========================================

Copy-paste this checklist to follow along!


PRE-DEPLOYMENT (Do this first):
==============================

[] 1. Get Discord Token
   - Go: https://discord.com/developers/applications
   - Create "New Application"
   - Tab "Bot" → "Add Bot"
   - Click "Copy" under TOKEN
   - Save this token somewhere safe!

[] 2. Invite Bot to Server
   - Tab "OAuth2" → "URL Generator"
   - Select scope: bot
   - Select permissions:
     [ ] Send Messages
     [ ] Embed Links
     [ ] Connect (voice)
     [ ] Speak (voice)
     [ ] Move Members
   - Copy URL → open in browser
   - Select server → Authorize

[] 3. Create Railway Account
   - Go: https://railway.app
   - Sign up with GitHub (recommended)

[] 4. Prepare Files (download from outputs)
   - railway_bot.py
   - Dockerfile
   - railway_requirements.txt
   - (optional) .env.example


DEPLOYMENT OPTIONS:
===================

CHOOSE ONE:

OPTION A: Direct Upload (EASIEST - 5 min)
-----------------------------------------

[] 1. Go Railway.app → Dashboard
[] 2. Click "New Project"
[] 3. Select "Empty Project"
[] 4. Click "Add Service" → "Docker"
[] 5. Click "Editor" tab
[] 6. Upload files:
   [] railway_bot.py
   [] Dockerfile
   [] railway_requirements.txt
[] 7. Click "Variables" tab
[] 8. Add variable:
   [] Name: DISCORD_TOKEN
   [] Value: [your_token_here]
[] 9. Save
[] 10. Check "Deployments" tab
[] 11. Wait for green status
[] 12. Done!


OPTION B: GitHub Integration (BEST - 10 min)
---------------------------------------------

[] 1. Create GitHub Repository:
   - New repo on github.com
   - Clone locally: git clone [url]
   - Copy 3 files into repo
   - Create .env.example
   - Create .gitignore (use template)
   - Create README.md

[] 2. Push to GitHub:
   git add .
   git commit -m "Discord music bot initial commit"
   git branch -M main
   git push -u origin main

[] 3. Go Railway.app → Dashboard
[] 4. Click "New Project"
[] 5. "Deploy from GitHub"
[] 6. Select your repository
[] 7. Railway auto-creates service
[] 8. Click "Variables" tab
[] 9. Add DISCORD_TOKEN:
   [] Name: DISCORD_TOKEN
   [] Value: [your_token_here]
[] 10. Save (auto-deploys)
[] 11. Check "Deployments" tab
[] 12. Done!


POST-DEPLOYMENT (Testing):
==========================

[] 1. Check Railway Logs
   - Dashboard → Service → Logs tab
   - Look for: "Bot logged in as..."
   - Should be GREEN status

[] 2. Discord Test - Basic
   [] Open Discord server
   [] Type: !hello
   [] Bot should reply: "Hello @YourName!"

[] 3. Discord Test - Roll
   [] Type: !roll
   [] Bot should reply with random number

[] 4. Discord Test - Voice
   [] Join voice channel in Discord
   [] Type: !join
   [] Bot should join voice channel
   [] No errors in logs?

[] 5. Discord Test - Music
   [] Type: !play despacito
   [] Bot should reply: "Queued: Despacito..."
   [] Wait 5 seconds
   [] Listen for music
   [] Music playing?

[] 6. Discord Test - Controls
   [] Type: !pause
   [] Music pauses?
   [] Type: !resume
   [] Music resumes?
   [] Type: !skip
   [] Next track plays?

[] 7. Discord Test - Queue
   [] Type: !queue
   [] Shows current track?
   [] Shows upcoming tracks?

[] 8. Check Logs Again
   [] Any ERROR messages?
   [] Normal operation logged?
   [] No issues?


TROUBLESHOOTING:
================

If something fails, check in order:

[] 1. Railway Logs
   - Dashboard → Service → Logs
   - What error message?
   - Is service running (green)?

[] 2. Discord Token
   - Correct token added to Variables?
   - Token not expired?
   - Try regenerate in Developer Portal

[] 3. Bot Permissions
   - Bot invited with correct scopes?
   - Bot has permissions in channel?
   - Try re-invite

[] 4. Discord Intents
   - Developer Portal → Your app → Bot
   - "Message Content Intent" enabled?
   - "Server Members Intent" enabled?

[] 5. FFmpeg (probably fine)
   - Dockerfile installs it automatically
   - Usually not an issue on Railway

[] 6. Restart Service
   - Railway Dashboard → Service
   - Click restart button
   - Redeploy


FILE CHECKLIST:
===============

Make sure you have:

[] railway_bot.py (main bot code)
[] Dockerfile (Docker configuration)
[] railway_requirements.txt (dependencies)

Optional but recommended:
[] .env.example (template - don't upload actual .env)
[] .gitignore (if using GitHub)
[] README.md (documentation)


COMMAND QUICK REFERENCE:
=======================

Test these commands to verify bot works:

!hello                    (basic test)
!roll                     (number test)
!roll 1000                (custom range)
!join                     (voice join)
!play despacito           (search and play)
!play <youtube_url>       (direct URL)
!pause                    (pause music)
!resume                   (resume music)
!skip                     (next track)
!queue                    (show queue)
!queue clear              (clear queue)
!leave                    (bot leaves voice)
!help                     (show all commands)


IMPORTANT NOTES:
================

Railway is MUCH BETTER than Replit/Vercel because:
✓ Free $5/month credit
✓ FFmpeg pre-installed
✓ Better voice support
✓ 24/7 guaranteed
✓ Faster deployment
✓ Easier setup

No manual FFmpeg install needed!
Everything automatic!


DAILY OPERATION:
================

After bot is deployed:

1. Bot runs 24/7 automatically
2. Railway handles uptime
3. No keep-alive script needed
4. No manual restart needed
5. Logs available anytime

If bot crashes:
- Railway auto-restarts
- Check logs for cause
- Fix and redeploy


SUPPORT:
========

If stuck:

1. Check RAILWAY_SETUP_GUIDE.md
2. Check Railway logs
3. Check Discord Developer Portal settings
4. Ask in Railway Discord: discord.gg/railway
5. Ask in discord.py Discord: discord.gg/dpy


UPDATING BOT:
=============

To update code:

If using GitHub:
   git push origin main
   (Railway auto-redeploys)

If direct upload:
   Edit file in Railway editor
   Save (auto-redeploys)


SUCCESS!
========

When you see in logs:

"Bot logged in as MusicBot"
"Connected to X server(s)"

Congratulations! Bot is online!

Test with !hello in Discord.
Music should work!


NEXT STEPS:
===========

Bot is now online 24/7!

You can:
[] Customize bot name/avatar
[] Add more features
[] Invite to more servers
[] Monitor via Railway dashboard
[] Update code anytime

Enjoy your music bot!


TIME ESTIMATES:
===============

Direct Upload:
- Get token: 5 min
- Create Railway account: 2 min
- Deploy: 5 min
- Test: 5 min
TOTAL: 17 minutes

GitHub Integration:
- Get token: 5 min
- Create repo: 5 min
- Push to GitHub: 2 min
- Deploy from Railway: 3 min
- Test: 5 min
TOTAL: 20 minutes


That's it! Good luck!
