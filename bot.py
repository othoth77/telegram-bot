import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import os
import tempfile
import requests
import base64

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
# ANALYSE FACTURE AVEC GOOGLE VISION
# ============================================================
def analyser_facture_vision(image_bytes):
    scopes_vision = ["https://www.googleapis.com/auth/cloud-vision"]
    creds_vision = ServiceAccountCredentials.from_json_keyfile_name(temp_credentials_path, scopes_vision)
    creds_vision.get_access_token()
    access_token = creds_vision.access_token

    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    url = "https://vision.googleapis.com/v1/images:annotate"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    body = {
        "requests": [{
            "image": {"content": image_base64},
            "features": [{"type": "TEXT_DETECTION"}]
        }]
    }

    response = requests.post(url, headers=headers, json=body)
    print(f"Vision API status: {response.status_code}")
    print(f"Vision API response: {response.text[:500]}")
    
    result = response.json()

    if "responses" in result and result["responses"]:
        texte = result["responses"][0].get("fullTextAnnotation", {}).get("text", "")
        print(f"Texte extrait: {texte[:200]}")
        return texte
    return ""

def extraire_donnees_facture(texte):
    import re
    
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

    for i, ligne in enumerate(lignes):
        ligne_lower = ligne.lower()

        if any(x in ligne_lower for x in ["facture n", "invoice n", "n° facture", "fact n", "facture:"]):
            match = re.search(r'[\w\-\/]+\d+[\w\-\/]*', ligne)
            if match:
                donnees["numero_facture"] = match.group()

        if any(x in ligne_lower for x in ["ttc", "total ttc", "net à payer", "total tva"]):
            match = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match:
                donnees["montant_ttc"] = match.group().strip()

        if any(x in ligne_lower for x in ["ht", "hors taxe", "base ht", "total ht"]):
            match = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match:
                donnees["montant_ht"] = match.group().strip()

        if any(x in ligne_lower for x in ["tva", "taxe", "vat"]):
            match_pct = re.search(r'(\d+)\s*%', ligne)
            if match_pct:
                donnees["tva_pct"] = match_pct.group(1)
            match_montant = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match_montant and not donnees["montant_tva"]:
                donnees["montant_tva"] = match_montant.group().strip()

        if any(x in ligne_lower for x in ["client:", "bill to", "facturer à", "nom client"]):
            if i + 1 < len(lignes):
                donnees["client"] = lignes[i + 1].strip()

        if "eur" in ligne_lower or "€" in ligne:
            donnees["devise"] = "EUR"
        elif "usd" in ligne_lower or "$" in ligne:
            donnees["devise"] = "USD"
        elif "tnd" in ligne_lower or "dt" in ligne_lower:
            donnees["devise"] = "TND"

    for ligne in lignes[:5]:
        if ligne.strip():
            donnees["fournisseur"] = ligne.strip()
            break

    donnees["description"] = texte[:100].replace('\n', ' ').strip()

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
        print(f"Image téléchargée: {len(image_bytes)} bytes")

        texte = analyser_facture_vision(image_bytes)
        
        if not texte:
            bot.reply_to(message, "❌ Je n'ai pas pu lire le texte. Erreur Vision API — vérifie les logs Railway.")
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
            f"✅ Facture enregistrée !\n\n"
            f"🏢 Fournisseur: {donnees['fournisseur']}\n"
            f"👤 Client: {donnees['client']}\n"
            f"🔢 N° Facture: {donnees['numero_facture']}\n"
            f"💰 Montant HT: {donnees['montant_ht']} {donnees['devise']}\n"
            f"🏷️ TVA: {donnees['tva_pct']}% ({donnees['montant_tva']} {donnees['devise']})\n"
            f"💵 Total TTC: {donnees['montant_ttc']} {donnees['devise']}"
        )

    except Exception as e:
        print(f"ERREUR: {str(e)}")
        bot.reply_to(message, f"❌ Erreur détaillée: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    utilisateur = message.from_user.first_name
    texte = message.text
    sheet.append_row([date, "", utilisateur, "", texte, "", "", "", "", ""])
    bot.reply_to(message, f"✅ Message enregistré !\n📅 {date}")

print("🤖 Bot factures démarré avec succès !")
bot.polling(none_stop=True)
