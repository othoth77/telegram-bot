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

# Ajouter les en-têtes si la feuille est vide
if sheet.row_count == 0 or sheet.cell(1, 1).value is None:
    sheet.append_row(["Date", "Fournisseur", "Client", "Numéro Facture", "Description", "Montant HT", "TVA %", "Montant TVA", "Montant TTC", "Devise"])

# ============================================================
# ANALYSE FACTURE AVEC GOOGLE VISION
# ============================================================
def analyser_facture_vision(image_bytes):
    """Envoie l'image à Google Vision API et récupère le texte"""
    # Utiliser les credentials pour obtenir un token
    import google.auth
    import google.auth.transport.requests
    
    scopes_vision = ["https://www.googleapis.com/auth/cloud-vision"]
    creds_vision = ServiceAccountCredentials.from_json_keyfile_name(temp_credentials_path, scopes_vision)
    creds_vision.get_access_token()
    access_token = creds_vision.access_token

    # Encoder l'image en base64
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    # Appel API Vision
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
    result = response.json()

    if "responses" in result and result["responses"]:
        texte = result["responses"][0].get("fullTextAnnotation", {}).get("text", "")
        return texte
    return ""

def extraire_donnees_facture(texte):
    """Extrait les données importantes du texte de la facture"""
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

        # Numéro de facture
        if any(x in ligne_lower for x in ["facture n", "invoice n", "n° facture", "fact n", "facture:"]):
            match = re.search(r'[\w\-\/]+\d+[\w\-\/]*', ligne)
            if match:
                donnees["numero_facture"] = match.group()

        # Montant TTC
        if any(x in ligne_lower for x in ["ttc", "total ttc", "net à payer", "total tva"]):
            match = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match:
                donnees["montant_ttc"] = match.group().strip()

        # Montant HT
        if any(x in ligne_lower for x in ["ht", "hors taxe", "base ht", "total ht"]):
            match = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match:
                donnees["montant_ht"] = match.group().strip()

        # TVA
        if any(x in ligne_lower for x in ["tva", "taxe", "vat"]):
            match_pct = re.search(r'(\d+)\s*%', ligne)
            if match_pct:
                donnees["tva_pct"] = match_pct.group(1)
            match_montant = re.search(r'[\d\s]+[,.]?\d*', ligne)
            if match_montant and not donnees["montant_tva"]:
                donnees["montant_tva"] = match_montant.group().strip()

        # Client
        if any(x in ligne_lower for x in ["client:", "bill to", "facturer à", "nom client"]):
            if i + 1 < len(lignes):
                donnees["client"] = lignes[i + 1].strip()

        # Devise
        if "eur" in ligne_lower or "€" in ligne:
            donnees["devise"] = "EUR"
        elif "usd" in ligne_lower or "$" in ligne:
            donnees["devise"] = "USD"
        elif "tnd" in ligne_lower or "dt" in ligne_lower:
            donnees["devise"] = "TND"

    # Fournisseur = première ligne non vide
    for ligne in lignes[:5]:
        if ligne.strip():
            donnees["fournisseur"] = ligne.strip()
            break

    # Description = texte résumé
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
        "📸 Envoie-moi une photo d'une facture et je vais extraire automatiquement toutes les informations et les enregistrer dans Google Sheets !\n\n"
        "📝 Tu peux aussi envoyer un message texte pour l'enregistrer directement."
    )

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.reply_to(message, "📸 Photo reçue ! Analyse en cours... ⏳")
    
    try:
        # Télécharger la photo
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        image_bytes = requests.get(file_url).content

        # Analyser avec Google Vision
        texte = analyser_facture_vision(image_bytes)
        
        if not texte:
            bot.reply_to(message, "❌ Je n'ai pas pu lire le texte de cette image. Essaie avec une photo plus claire.")
            return

        # Extraire les données
        donnees = extraire_donnees_facture(texte)
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Enregistrer dans Google Sheets
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

        # Répondre avec un résumé
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
        bot.reply_to(message, f"❌ Erreur: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    utilisateur = message.from_user.first_name
    texte = message.text
    sheet.append_row([date, "", utilisateur, "", texte, "", "", "", "", ""])
    bot.reply_to(message, f"✅ Message enregistré dans Google Sheets !\n📅 {date}")

print("🤖 Bot factures démarré avec succès !")
bot.polling(none_stop=True)
