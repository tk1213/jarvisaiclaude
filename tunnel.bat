@echo off
rem Public https URL for the LINE webhook: run this next to start.bat.
rem Needs cloudflared once: winget install --id Cloudflare.cloudflared
rem Copy the https://....trycloudflare.com address it prints, add /line/webhook,
rem and paste it into LINE Developers Console > Messaging API > Webhook URL (it changes on every run).
cloudflared tunnel --url http://localhost:8000
pause
