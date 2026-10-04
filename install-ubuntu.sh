#!/usr/bin/env bash
# Install JARVIS on Ubuntu Desktop 24.04 from a backup folder (the one backup.bat makes in D:\JarvisClaudeBackup\<date>).
#
#   bash install-ubuntu.sh "/media/$USER/<USB>/<date>"
#
# Run it as the normal user (not with sudo); it asks for the password when it needs root. Safe to run again:
# steps that are already done are skipped, and existing data (.env, databases) is never overwritten.
set -euo pipefail

REPO_URL="https://github.com/tk1213/jarvisaiclaude.git"
APP_DIR="$HOME/jarvisclaude"
BACKEND="$APP_DIR/backend"
BACKUP_DIR="$HOME/JarvisClaudeBackup"
PORT=8765

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; WARNINGS+=("$*"); }
die() { printf '\033[31m  ✗ %s\033[0m\n' "$*"; exit 1; }
WARNINGS=()

[[ $EUID -ne 0 ]] || die "อย่ารันด้วย sudo ให้รันเป็นผู้ใช้ปกติ: bash install-ubuntu.sh <โฟลเดอร์สำรอง>"
# shellcheck source=/dev/null
[[ -r /etc/os-release ]] && . /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || warn "เครื่องนี้ไม่ใช่ Ubuntu (${PRETTY_NAME:-ไม่ทราบ}) สคริปต์ทดสอบกับ Ubuntu 24.04"

SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  read -r -p "ที่อยู่โฟลเดอร์สำรอง (ลากโฟลเดอร์มาวางในหน้าต่างนี้ได้): " SRC
fi
SRC="${SRC%/}"
SRC="${SRC//\'/}"
[[ -d "$SRC" ]] || die "ไม่พบโฟลเดอร์ $SRC"
for f in jarvis-code.bundle .env jarvis.db catalog.db; do
  [[ -e "$SRC/$f" ]] || warn "ในโฟลเดอร์สำรองไม่มี $f"
done

sudo -v || die "ต้องใช้รหัสผ่านของเครื่องนี้ (sudo)"

# --- 1. Programs -----------------------------------------------------------------------------------
step "1/8 ติดตั้งโปรแกรมพื้นฐาน (git, Python, sqlite)"
sudo apt-get update -y
sudo apt-get install -y git curl wget ca-certificates python3-venv python3-pip sqlite3
ok "ติดตั้งแล้ว"

step "2/8 Node.js 22 (สำหรับ build หน้าเว็บ)"
node_major() { node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/'; }
if [[ "$(node_major || echo 0)" -ge 22 ]]; then
  ok "มี Node.js $(node -v) แล้ว"
else
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
  ok "ติดตั้ง Node.js $(node -v)"
fi

step "3/8 Google Chrome (ไมค์และเสียงของ Dashboard)"
if command -v google-chrome >/dev/null; then
  ok "มี Chrome แล้ว"
else
  tmp=$(mktemp -d)
  wget -q -O "$tmp/chrome.deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y "$tmp/chrome.deb"
  rm -rf "$tmp"
  ok "ติดตั้ง Chrome แล้ว"
fi

# --- 2. Code and data ------------------------------------------------------------------------------
step "4/8 โค้ดและข้อมูลจาร์วิส"
if [[ -d "$APP_DIR/.git" ]]; then
  ok "มีโค้ดที่ $APP_DIR แล้ว (ไม่ดึงใหม่)"
elif [[ -f "$SRC/jarvis-code.bundle" ]]; then
  git clone "$SRC/jarvis-code.bundle" "$APP_DIR"
  git -C "$APP_DIR" checkout main
  git -C "$APP_DIR" remote set-url origin "$REPO_URL"
  ok "เอาโค้ดจากไฟล์สำรองแล้ว"
else
  git clone "$REPO_URL" "$APP_DIR"
  ok "ดึงโค้ดจาก GitHub แล้ว"
fi
# No password prompt: a private repository just falls back to the code from the backup.
if GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$APP_DIR" pull --ff-only -q origin main 2>/dev/null; then
  ok "อัปเดตโค้ดเป็นล่าสุดจาก GitHub แล้ว"
else
  warn "ดึงโค้ดล่าสุดจาก GitHub ไม่ได้ (ใช้โค้ดจากไฟล์สำรอง) ภายหลังสั่ง: cd ~/jarvisclaude && git pull"
fi

restore() { # restore <file in backup> <destination> [optional]: never overwrites existing data
  local from="$SRC/$1" to="$2" optional="${3:-}"
  if [[ -e "$to" ]]; then
    ok "$1: มีอยู่แล้วที่ $to (ไม่เขียนทับ)"
  elif [[ -e "$from" ]]; then
    mkdir -p "$(dirname "$to")"
    cp "$from" "$to"
    ok "$1 -> $to"
  elif [[ -z "$optional" ]]; then
    warn "ไม่มี $1 ในโฟลเดอร์สำรอง"
  fi
}
restore .env "$BACKEND/.env"
restore jarvis.db "$BACKEND/jarvis.db"
restore catalog.db "$BACKEND/data/flowaccount/catalog.db"
restore account.db "$BACKEND/data/account/account.db" optional # backups made before the Account page have none
chmod 600 "$BACKEND/.env" 2>/dev/null || true

if [[ -f "$BACKEND/.env" ]]; then
  # Backups go to a Linux folder instead of D:\JarvisClaudeBackup.
  if grep -q '^BACKUP_DIR=' "$BACKEND/.env"; then
    sed -i "s|^BACKUP_DIR=.*|BACKUP_DIR=$BACKUP_DIR|" "$BACKEND/.env"
  else
    printf '\nBACKUP_DIR=%s\n' "$BACKUP_DIR" >>"$BACKEND/.env"
  fi
  sed -i 's/\r$//' "$BACKEND/.env" # Windows line endings
  ok "ตั้ง BACKUP_DIR=$BACKUP_DIR ใน .env"
  # Show only the setting names that still point at a Windows drive, never their values (secrets).
  windows_paths=$(grep -E '^[A-Z_]+=["'"'"']?([a-z]+:///)?[A-Za-z]:[\\/]' "$BACKEND/.env" | cut -d= -f1 | tr '\n' ' ' || true)
  if [[ -n "$windows_paths" ]]; then
    warn "ใน .env ยังมีค่าที่อ้างไดรฟ์ Windows: ${windows_paths}แก้ด้วย: nano ~/jarvisclaude/backend/.env"
  fi
fi

# --- 3. Install and build --------------------------------------------------------------------------
step "5/8 ติดตั้งระบบจาร์วิส (Python) และ build หน้าเว็บ"
[[ -x "$BACKEND/.venv/bin/python" ]] || python3 -m venv "$BACKEND/.venv"
"$BACKEND/.venv/bin/pip" install -q --upgrade pip
"$BACKEND/.venv/bin/pip" install -q -e "${BACKEND}[dev]"
ok "ติดตั้ง backend แล้ว"
(cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund && npm run build)
ok "build หน้าเว็บแล้ว"

# --- 4. Start on boot ------------------------------------------------------------------------------
step "6/8 ให้จาร์วิสเปิดเองทุกครั้งที่เปิดเครื่อง (systemd)"
sudo tee /etc/systemd/system/jarvis.service >/dev/null <<EOF
[Unit]
Description=JARVIS
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$BACKEND
ExecStart=$BACKEND/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable jarvis >/dev/null 2>&1
sudo systemctl restart jarvis
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  ok "จาร์วิสทำงานแล้วที่ http://localhost:$PORT"
else
  warn "จาร์วิสยังไม่ตอบ ดู log ด้วย: journalctl -u jarvis -n 50"
fi

# --- 5. Daily backup -------------------------------------------------------------------------------
step "7/8 สำรองข้อมูลอัตโนมัติวันละครั้ง (cron)"
mkdir -p "$BACKUP_DIR"
backup_cmd="cd $BACKEND && .venv/bin/python -m app.scripts.backup --auto"
{
  crontab -l 2>/dev/null | grep -v 'app.scripts.backup' || true
  echo "0 12 * * * $backup_cmd"
  echo "@reboot sleep 600 && $backup_cmd"
} | crontab -
ok "ตั้งเวลาแล้ว: เที่ยงวัน และ 10 นาทีหลังเปิดเครื่อง (เก็บที่ $BACKUP_DIR)"
if (cd "$BACKEND" && .venv/bin/python -m app.scripts.backup >/dev/null 2>&1); then
  ok "สำรองครั้งแรกแล้ว: $BACKUP_DIR/$(date +%F)"
else
  warn "สำรองครั้งแรกไม่สำเร็จ ดู $BACKUP_DIR/backup.log"
fi

# --- 6. Desktop: no sleep, Chrome on login, cloudflared ---------------------------------------------
step "8/8 ตั้งค่าเครื่องให้เปิดใช้งานตลอด"
if command -v gsettings >/dev/null && gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null; then
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || true
  gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
  ok "ปิดการพักหน้าจอ การล็อก และการหลับอัตโนมัติแล้ว"
else
  warn "ตั้งค่าไม่ให้เครื่องหลับไม่ได้ ตั้งเองที่ Settings > Power"
fi
mkdir -p "$HOME/.config/autostart"
cat >"$HOME/.config/autostart/jarvis-dashboard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=JARVIS Dashboard
Exec=sh -c "sleep 15 && google-chrome http://localhost:$PORT"
X-GNOME-Autostart-enabled=true
EOF
ok "Chrome จะเปิด Dashboard เองทุกครั้งที่เข้าเครื่อง"
if command -v cloudflared >/dev/null; then
  ok "มี cloudflared แล้ว"
else
  tmp=$(mktemp -d)
  wget -q -O "$tmp/cloudflared.deb" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo apt-get install -y "$tmp/cloudflared.deb"
  rm -rf "$tmp"
  ok "ติดตั้ง cloudflared แล้ว"
fi
if systemctl is-active --quiet cloudflared 2>/dev/null; then
  ok "Cloudflare tunnel ทำงานอยู่แล้ว"
else
  warn "ยังไม่ได้เชื่อม Cloudflare tunnel (LINE ยังใช้ไม่ได้) ดูขั้นที่เหลือด้านล่าง"
fi

# --- Done ------------------------------------------------------------------------------------------
step "เสร็จแล้ว"
cat <<EOF
  Dashboard:  http://localhost:$PORT  (ล็อกอินด้วยรหัสเดิม)
  ดู log:      journalctl -u jarvis -f
  หลัง git pull: cd ~/jarvisclaude/frontend && npm run build && sudo systemctl restart jarvis

  สิ่งที่ต้องทำเองอีกนิด:
  1. เครื่อง Windows เก่า: ปิด start.bat และรัน (PowerShell แบบ Administrator)  cloudflared.exe service uninstall
  2. Cloudflare Zero Trust > Networks > Tunnels > tunnel เดิม > Configure > Debian
     คัดลอกคำสั่ง  sudo cloudflared service install <token>  มารันที่นี่ แล้วลองส่งข้อความหาจาร์วิสใน LINE
  3. Settings > System > Users: เปิด Automatic Login (ไฟดับแล้ว Chrome จะเปิด Dashboard เอง)
  4. BIOS: ตั้ง "Restore on AC Power Loss" เป็น Power On
  5. ครั้งแรกที่กดไมค์ใน Chrome ให้กด Allow
EOF
if ((${#WARNINGS[@]})); then
  printf '\n\033[33m  ข้อที่ต้องตรวจ:\033[0m\n'
  for w in "${WARNINGS[@]}"; do printf '\033[33m  - %s\033[0m\n' "$w"; done
fi
