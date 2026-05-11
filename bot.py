import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import os
import tempfile

# ============================================================
# CONFIGURATION
# ============================================================
TOKEN = "7598630137:AAEMFZDHazIVeTRbRO7I6Iw8gwQ_hVTzf-g"
SHEET_ID = "1vcTv6AcNsHXUg8J0j_lJBBLL1053aIxO5Hua9Rm8-jQ"

# ============================================================
# CONNEXION GOOGLE SHEETS via variable d'environnement
# ============================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Lire les credentials depuis la variable d'environnement
credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)

# Créer un fichier temporaire pour les credentials
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(credentials_dict, f)
    temp_credentials_path = f.name

creds = ServiceAccountCredentials.from_json_keyfile_name(temp_credentials_path, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# ============================================================
# BOT TELEGRAM
# ============================================================
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    utilisateur = message.from_user.first_name
    texte = message.text

    sheet.append_row([date, utilisateur, texte])
    bot.reply_to(message, f"✅ Message enregistré dans Google Sheets !\n📅 {date}")

print("🤖 Bot démarré avec succès !")
bot.polling(none_stop=True)
