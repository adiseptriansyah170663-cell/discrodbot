DISCORD MUSIC BOT - RAILWAY DEPLOYMENT GUIDE
=============================================

Railway adalah platform TERBAIK untuk Discord music bot:
- Free $5/month credit
- 24/7 uptime
- FFmpeg pre-configured
- Much more reliable than Replit
- Better voice support

PREREQUISITES:
==============

Siapkan sebelum mulai:

1. Discord Bot Token
   - Go: https://discord.com/developers/applications
   - Create "New Application"
   - Tab "Bot" → Add Bot
   - Copy TOKEN

2. Discord Server
   - Sudah punya atau buat baru

3. Railway Account
   - Go: https://railway.app
   - Sign up dengan GitHub (recommended)

4. (Optional) GitHub Repository
   - For auto-deploy
   - But Railway supports direct upload too

STEP-BY-STEP SETUP:
===================

STEP 1: Invite Bot to Discord Server

1. Discord Developer Portal → Your app
2. Tab "OAuth2" → "URL Generator"
3. Select scopes: bot
4. Select permissions:
   - Send Messages
   - Embed Links
   - Connect (voice)
   - Speak (voice)
   - Move Members
5. Copy URL → Open in browser
6. Select server → Authorize

STEP 2: Create Railway Project

Option A: Direct Upload (EASIEST)

   1. Go: https://railway.app
   2. Dashboard → "New Project"
   3. Select "Empty Project"
   4. Click "Add Service" → "Docker"
   5. Done! Go to STEP 3

Option B: GitHub Integration

   1. Push bot files to GitHub:
      - railway_bot.py
      - Dockerfile
      - railway_requirements.txt
   
   2. Go: https://railway.app
   3. Dashboard → "New Project"
   4. "Deploy from GitHub"
   5. Select your repository
   6. Railway auto-deploys

STEP 3: Upload Files (if using direct upload)

In Railway dashboard, for your Docker service:

1. Click "Editor" tab
2. Create/upload files:
   - railway_bot.py
   - Dockerfile
   - railway_requirements.txt

Or use Railway CLI (advanced)

STEP 4: Configure Environment Variables

In Railway dashboard:

1. Click your service
2. Click "Variables" tab
3. Add new variable:
   - Name: DISCORD_TOKEN
   - Value: [Your Discord bot token]
4. Save

STEP 5: Deploy

1. Railway auto-deploys after files uploaded
2. Check "Deployments" tab
3. Wait for deployment to finish
4. Check logs for "Bot logged in as..."

STEP 6: Test Bot

In Discord:
1. Type: !hello
   (bot should reply)

2. Join voice channel

3. Type: !play despacito
   (bot should queue and reply)

4. Wait 5 seconds
   (music should play)

THAT'S IT! Bot is online 24/7 on Railway!


RAILWAY ADVANTAGES:
===================

vs Replit:
✓ Better voice connection stability
✓ FFmpeg pre-installed and configured
✓ No need for manual FFmpeg install
✓ Better resource allocation
✓ More reliable 24/7 operation
✓ Faster startup time

vs Vercel:
✓ Supports persistent connections
✓ No time limits
✓ Designed for always-on apps
✓ Better for Discord bots

vs Heroku:
✓ Heroku discontinued free tier
✓ Railway still free ($5/month)
✓ Similar reliability
✓ Better pricing


DEPLOYMENT OPTIONS:
===================

Option 1: Direct Upload (EASIEST - 5 minutes)

Files needed:
- railway_bot.py
- Dockerfile
- railway_requirements.txt

Steps:
1. New Project → Empty
2. Add Docker service
3. Upload files
4. Add DISCORD_TOKEN to Variables
5. Done!

Option 2: GitHub Integration (BEST - 10 minutes)

Procedure:
1. Create GitHub repo
2. Push files:
   git push origin main
3. Railway → New Project
4. "Deploy from GitHub"
5. Select repo
6. Auto-deploy!

Benefits:
- Auto-redeploy on push
- Better version control
- Easy to collaborate


RAILWAY DOCKERFILE:
===================

What the Dockerfile does:

1. Uses Python 3.11
2. Installs FFmpeg (important!)
3. Installs audio libraries
4. Installs Python dependencies
5. Copies bot code
6. Runs bot

Everything configured for Discord.py voice!


TROUBLESHOOTING:
================

ISSUE 1: Deployment failed

Check:
1. Dockerfile syntax correct?
2. All files present?
3. requirements.txt valid Python packages?
4. DISCORD_TOKEN added to Variables?

Solution:
- Click "Logs" tab
- See error message
- Fix and re-upload

ISSUE 2: Bot won't start

Logs show error:
- "DISCORD_TOKEN not found"
  → Add to Variables

- "Module not found"
  → Check requirements.txt

- "FFmpeg not found"
  → Dockerfile handles this, redeploy

- Python error
  → Check railway_bot.py syntax

ISSUE 3: Bot starts but doesn't respond

Check:
1. Bot invited to server?
2. Token correct?
3. Message Content Intent enabled?
4. Bot role above other roles?

Solution:
- Re-invite bot with correct scopes
- Regenerate token if unsure
- Check Discord Developer Portal settings

ISSUE 4: No audio when playing music

Usually FFmpeg issue:
1. Check logs for FFmpeg error
2. Dockerfile installs FFmpeg automatically
3. If still fails, add to Variables:
   FFMPEG_PATH=/usr/bin/ffmpeg

ISSUE 5: Voice connection fails

Might be:
1. Permissions issue
2. Voice codec issue
3. Network timeout

Solutions:
- Restart Railway service
- Check Discord status page
- Try different voice channel


VIEWING LOGS:
=============

In Railway dashboard:

1. Click your service
2. Click "Logs" tab
3. See real-time logs

Look for:
- "Bot logged in as..." (good!)
- ERROR messages (bad)
- Connection info
- FFmpeg loaded

Example good output:
```
2024-01-15 10:30:45 - INFO - Starting Discord Music Bot...
2024-01-15 10:30:50 - INFO - Bot logged in as MusicBot
2024-01-15 10:30:50 - INFO - Connected to 5 server(s)
```


COMMANDS REFERENCE:
===================

!hello              Say hello
!roll [max]         Roll random number
!join               Join voice channel
!leave              Leave voice channel
!play <query>       Play music
!pause              Pause
!resume             Resume
!skip               Skip track
!queue / !q         Show queue
!clear              Clear queue
!help               Show commands

Examples:
!play despacito
!play https://youtu.be/kJQP7kiw9Fk
!play playlist name


UPDATING BOT:
=============

If you want to update code:

1. Edit railway_bot.py locally
2. If using GitHub:
   git add railway_bot.py
   git commit -m "Update bot"
   git push origin main
   (Railway auto-redeploys)

3. If direct upload:
   Replace railway_bot.py in Railway editor
   Save (auto-redeploys)

That's it! No downtime needed usually.


COST:
=====

Railway pricing:

Free tier:
- $5 free credit per month
- Enough for:
  - 1 Discord bot 24/7
  - Plus other services
  - Usually lasts whole month

If exceed $5:
- You can add payment method
- Or delete services to stay free

Most users stay within $5/month.


MONITORING:
===========

Check if bot is running:

In Railway dashboard:
- Status should be green
- Check last deployment

In Discord:
- Type !hello
- If bot replies, it's running

In logs:
- Check for errors
- Look for normal activity

Uptime:
- Railway shows deployment time
- Should be continuous


ADVANCED: CUSTOM DOMAIN:
========================

You can add custom status webpage:

1. Add Flask endpoint in bot
2. Railway provides domain
3. Monitor bot via web

Not necessary for music bot.
Just for advanced users.


.env FILE:
==========

Not needed for Railway!

Railway uses environment variables instead:
- More secure
- Better for production
- No .env file needed

Just add variables in Railway dashboard.


GITHUB INTEGRATION SETUP:
========================

If you want auto-deploy from GitHub:

STEP 1: Create GitHub Repository

   git init
   git add .
   git commit -m "Discord bot"
   git remote add origin https://github.com/YOUR_USERNAME/discord-bot.git
   git branch -M main
   git push -u origin main

STEP 2: Connect to Railway

   1. Railway Dashboard
   2. "New Project"
   3. "Deploy from GitHub"
   4. Select repository
   5. Done!

STEP 3: Modify and Re-deploy

   git add .
   git commit -m "Update"
   git push origin main
   
   Railway auto-deploys!

STEP 4: Add .gitignore

   Create .gitignore:
   .env
   __pycache__/
   *.pyc
   venv/


RECOMMENDED SETUP:
==================

For best experience:

1. Use GitHub integration
2. Files in GitHub:
   - railway_bot.py
   - Dockerfile
   - railway_requirements.txt
   - .env.example
   - .gitignore
   - README.md

3. Railway pulls from GitHub
4. Auto-deploys on push
5. Easy management!


SCALE UP (if needed):
====================

If bot gets popular:

1. Upgrade Railway plan
2. More memory/CPU available
3. Still using free credit
4. Or pay if exceed

For music bot, free tier usually enough
unless supporting 100+ servers.


SUPPORT:
========

Railway help:
- Docs: https://docs.railway.app
- Discord: https://discord.gg/railway
- Status: https://status.railway.app

Discord.py help:
- Docs: https://discordpy.readthedocs.io/
- Support: https://discord.gg/dpy


SUMMARY:
========

Railway is BEST for Discord music bot:

✓ Free $5/month
✓ 24/7 uptime
✓ FFmpeg included
✓ Easy setup (5-10 min)
✓ Auto-deploy from GitHub
✓ Reliable voice support
✓ Good community
✓ Scaling ready

Just 3 files needed:
- railway_bot.py
- Dockerfile
- railway_requirements.txt

Deploy now! Much better than Replit or Vercel.


Ready? Let's deploy!

Questions? Check logs first!
