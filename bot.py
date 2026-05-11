import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import os
import tempfile
import requests
import re
from PIL import Image
import pytesseract
import io

# ============================================================
# CONFIGURATION
# ============================================================
TOKEN = "7598630137:AAEMFZDHazIVeTRbRO7I6Iw8gwQ_hVTzf-g"
SHEET_ID = "1vcTv6AcNsHXUg8J0j_lJBBLL1053aIxO5Hua9Rm8-jQ"

# ============================================================
# CONNEXION GOOGLE SHEETS
# ============================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(credentials_dict, f)
    temp_credentials_path = f.name

creds = ServiceAccountCredentials.from_json_keyfile_name(temp_credentials_path, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# ============================================================
# ANALYSE FACTURE AVEC TESSERACT
# ============================================================
def analyser_image_tesseract(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    texte = pytesseract.image_to_string(image, lang='fra+eng')
    print(f"Texte extrait:\n{texte}")
    return texte

def extraire_montant(ligne):
    """Extrait un montant numérique d'une ligne (gère virgule et point)"""
    match = re.search(r'(\d[\d\s]*[.,]\d{2}|\d+)', ligne)
    if match:
        return match.group().strip().replace(' ', '')
    return ""

def extraire_donnees_facture(texte):
    donnees = {
        "fournisseur": "",
        "client": "",
        "numero_facture": "",
        "description": "",
        "montant_ht": "",
        "tva_pct": "",
        "montant_tva": "",
        "montant_ttc": "",
        "devise": "TND"
    }

    lignes = texte.split('\n')
    lignes_propres = [l.strip() for l in lignes if l.strip()]

    for i, ligne in enumerate(lignes_propres):
        ll = ligne.lower()

        # --- Numéro de facture ---
        if re.search(r'facture\s*n[°o]?\.?\s*[\w\-\/]+', ll):
            match = re.search(r'(\d{3,}[\/\-]\d{4}|\d{4,})', ligne)
            if match and not donnees["numero_facture"]:
                donnees["numero_facture"] = match.group()

        # --- Total HT (gère "Total NET HT", "Total HT", "Montant HT") ---
        if re.search(r'(total\s*net\s*ht|total\s*ht|montant\s*ht|net\s*ht)', ll):
            montant = extraire_montant(ligne)
            if montant and not donnees["montant_ht"]:
                donnees["montant_ht"] = montant

        # --- Total TTC ---
        if re.search(r'(total\s*ttc|net\s*[àa]\s*payer|ttc\s*:)', ll):
            montant = extraire_montant(ligne)
            if montant and not donnees["montant_ttc"]:
                donnees["montant_ttc"] = montant

        # --- TVA ---
        if re.search(r'\btva\b', ll):
            pct = re.search(r'(\d{1,2})\s*%', ligne)
            if pct and not donnees["tva_pct"]:
                donnees["tva_pct"] = pct.group(1)
            montant = extraire_montant(ligne)
            if montant and not donnees["montant_tva"]:
                donnees["montant_tva"] = montant

        # --- Client ---
        if re.search(r'(association|client\s*:|bill\s*to|facturer\s*[àa])', ll):
            if not donnees["client"]:
                donnees["client"] = ligne.strip()

        # --- Devise ---
        if 'tnd' in ll or 'dt' in ll or 'dinar' in ll:
            donnees["devise"] = "TND"
        elif 'eur' in ll or '€' in ligne:
            donnees["devise"] = "EUR"

    # --- Fournisseur = première ligne non vide significative ---
    for ligne in lignes_propres[:6]:
        if len(ligne) > 2 and not re.match(r'^\d+$', ligne) and 'facture' not in ligne.lower():
            donnees["fournisseur"] = ligne
            break

    # --- Description = première ligne produit/service ---
    for ligne in lignes_propres:
        if re.search(r'(transport|service|prestation|fourniture|livraison)', ligne.lower()):
            donnees["description"] = ligne[:100]
            break

    if not donnees["description"]:
        donnees["description"] = ' '.join(lignes_propres[:3])[:120]

    return donnees

# ============================================================
# BOT TELEGRAM
# ============================================================
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message,
        "👋 Bonjour ! Je suis ton bot de gestion de factures.\n\n"
        "📸 Envoie-moi une photo d'une facture !"
    )

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.reply_to(message, "📸 Photo reçue ! Analyse en cours... ⏳")

    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        image_bytes = requests.get(file_url).content

        texte = analyser_image_tesseract(image_bytes)

        if not texte.strip():
            bot.reply_to(message, "❌ Je n'ai pas pu lire le texte. Essaie avec une photo plus claire.")
            return

        donnees = extraire_donnees_facture(texte)
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sheet.append_row([
            date,
            donnees["fournisseur"],
            donnees["client"],
            donnees["numero_facture"],
            donnees["description"],
            donnees["montant_ht"],
            donnees["tva_pct"],
            donnees["montant_tva"],
            donnees["montant_ttc"],
            donnees["devise"]
        ])

        bot.reply_to(message,
            f"✅ Facture enregistrée dans Google Sheets !\n\n"
            f"🏢 Fournisseur: {donnees['fournisseur']}\n"
            f"👤 Client: {donnees['client']}\n"
            f"🔢 N° Facture: {donnees['numero_facture']}\n"
            f"💰 Montant HT: {donnees['montant_ht']} {donnees['devise']}\n"
            f"🏷️ TVA: {donnees['tva_pct']}% ({donnees['montant_tva']} {donnees['devise']})\n"
            f"💵 Total TTC: {donnees['montant_ttc']} {donnees['devise']}"
        )

    except Exception as e:
        print(f"ERREUR: {str(e)}")
        bot.reply_to(message, f"❌ Erreur: {str(e)}")

# ✅ Seulement les messages texte (pas les photos)
@bot.message_handler(func=lambda message: message.text is not None)
def handle_message(message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    utilisateur = message.from_user.first_name
    texte = message.text
    sheet.append_row([date, "", utilisateur, "", texte, "", "", "", "", ""])
    bot.reply_to(message, f"✅ Message enregistré !\n📅 {date}")

print("🤖 Bot factures démarré avec succès !")
bot.polling(none_stop=True)
