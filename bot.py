import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================
TOKEN = "7598630137:AAEMFZDHazIVeTRbRO7I6Iw8gwQ_hVTzf-g"
SHEET_ID = "1vcTv6AcNsHXUg8J0j_lJBBLL1053aIxO5Hua9Rm8-jQ"
CREDENTIALS_FILE = "credentials.json"

# ============================================================
# CONNEXION GOOGLE SHEETS
# ============================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# ============================================================
# BOT TELEGRAM
# ============================================================
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Récupérer les informations du message
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    utilisateur = message.from_user.first_name
    texte = message.text

    # Ajouter dans Google Sheets
    sheet.append_row([date, utilisateur, texte])

    # Répondre à l'utilisateur
    bot.reply_to(message, f"✅ Message enregistré dans Google Sheets !\n📅 {date}")

print("🤖 Bot démarré avec succès !")
bot.polling(none_stop=True)
