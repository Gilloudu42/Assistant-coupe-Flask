import os
import re
import requests
from flask import Flask, render_template, jsonify, send_from_directory, request, Response, redirect
import frontmatter
from dotenv import load_dotenv
import google.generativeai as genai
import PIL.Image
import io
import base64

from dotenv import load_dotenv

if os.path.exists(".env.vercel.production"):
    load_dotenv(".env.vercel.production")
if os.path.exists(".env.vercel.local"):
    load_dotenv(".env.vercel.local")
else:
    load_dotenv()

app = Flask(__name__)
DATA_DIR = os.path.join(app.root_path, 'data', 'defauts')

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def check_auth(username, password):
    env_user = os.environ.get("SITE_USER", "").strip()
    env_pass = os.environ.get("SITE_PASS", "").strip()
    return username == env_user and password == env_pass

def authenticate():
    return Response(
        'Accès restreint. Veuillez entrer vos identifiants.', 401,
        {'WWW-Authenticate': 'Basic realm="Assistant Coupe Secure"'}
    )

@app.before_request
def require_auth():
    # Si les variables ne sont pas définies en ligne, on laisse public
    if not os.environ.get("SITE_USER", "").strip() or not os.environ.get("SITE_PASS", "").strip():
        return
        
    # Ne pas bloquer le manifest PWA et les fichiers médias (pour les balises audio/video des mobiles)
    if request.path == '/manifest.json' or request.path.startswith('/data/defauts/'):
        return

    # Check for X-User header (used by the new multi-user system)
    user_header = request.headers.get('X-User')
    if user_header:
        # For now, we trust the header if SITE_USER/SITE_PASS are set
        # In a real app, we'd verify this against a token or Supabase Auth
        return
        
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

def get_defauts():
    results = []
    
    # Check Supabase first
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            response = requests.get(f"{SUPABASE_URL}/rest/v1/defauts", headers=get_supabase_headers(), verify=False)
            if response.status_code == 200:
                for row in response.json():
                    folder = row.get("slug")
                    
                    photos = []
                    audio = row.get("audio") or ""
                    
                    # Fetch files from Supabase Storage
                    storage_url = f"{SUPABASE_URL}/storage/v1/object/list/medias"
                    post_data = {"prefix": f"{folder}/"}
                    # The storage API requires the bearer token
                    storage_res = requests.post(storage_url, headers=get_supabase_headers(), json=post_data, verify=False)
                    if storage_res.status_code == 200:
                        for item in storage_res.json():
                            filename = item.get('name')
                            if not filename or filename == '.emptyFolderPlaceholder': continue
                            if re.search(r'\.(jpg|jpeg|png|gif)$', filename, re.IGNORECASE):
                                photos.append(filename)
                            elif filename.endswith('.m4a'):
                                audio = filename
                                
                    defaut_data = {
                        "id": row.get("id"),
                        "slug": row.get("slug"),
                        "content": row.get("content"),
                        "titre": row.get("titre"),
                        "date_transcription": row.get("date_transcription"),
                        "audio": audio,
                        "photos": photos
                    }
                    results.append(defaut_data)
        except Exception as e:
            print(f"Error fetching from Supabase: {e}", flush=True)
            
    # For local development if Supabase fails or not configured
    if not results and os.path.exists(DATA_DIR):
        for folder in os.listdir(DATA_DIR):
            folder_path = os.path.join(DATA_DIR, folder)
            if not os.path.isdir(folder_path):
                continue
    
            files = os.listdir(folder_path)
            md_file = next((f for f in files if f.endswith('.md')), None)
    
            if md_file:
                full_path = os.path.join(folder_path, md_file)
                with open(full_path, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                
                photos = [f for f in files if re.search(r'\.(jpg|jpeg|png|gif)$', f, re.IGNORECASE)]
                audio = next((f for f in files if f.endswith('.m4a')), None)
    
                defaut_data = {
                    "id": folder.lower().replace(" ", "-"),
                    "slug": folder,
                    "content": post.content,
                    "photos": photos,
                    "audio": audio
                }
                defaut_data.update(post.metadata)
                results.append(defaut_data)
                
    return results

@app.route('/')
def index():
    return send_from_directory(os.path.join(app.root_path, 'templates'), 'index.html')

@app.route('/api/defauts')
def api_defauts():
    defauts = get_defauts()
    return jsonify(defauts)

import urllib.parse

@app.route('/api/defauts/<path:slug>')
def api_defaut_detail(slug):
    slug = urllib.parse.unquote(slug)
    defauts = get_defauts()
    for d in defauts:
        if d['slug'] == slug or d['id'] == slug:
            return jsonify(d)
    return jsonify({"error": "Defaut not found", "slug": slug}), 404

@app.route('/data/defauts/<path:slug>/<path:filename>')
def serve_media(slug, filename):
    slug = urllib.parse.unquote(slug)
    filename = urllib.parse.unquote(filename)
    if SUPABASE_URL:
        encoded_slug = urllib.parse.quote(slug)
        encoded_filename = urllib.parse.quote(filename)
        return redirect(f"{SUPABASE_URL}/storage/v1/object/public/medias/{encoded_slug}/{encoded_filename}")
        
    folder_path = os.path.join(DATA_DIR, slug)
    return send_from_directory(folder_path, filename)

@app.route('/api/analyze-image', methods=['POST'])
def analyze_image():
    if not GEMINI_API_KEY:
        return jsonify({"error": "Gemini API key not configured"}), 500
        
    try:
        data = request.json
        image_data = data.get('image') # Base64 string
        if not image_data:
            return jsonify({"error": "No image provided"}), 400
            
        # Extract base64 part
        if "," in image_data:
            image_data = image_data.split(",")[1]
            
        image_bytes = base64.b64decode(image_data)
        img = PIL.Image.open(io.BytesIO(image_bytes))
        
        # Get defects list to give context to the AI
        defauts = get_defauts()
        defects_info = []
        for d in defauts:
            title = d.get('titre', d.get('slug'))
            content = str(d.get('content', ''))[:1500] # Send almost the full content
            defects_info.append(f"- ID: '{d['slug']}', Titre: '{title}', Description: {content}")
            
        defects_list_str = "\n\n".join(defects_info)
        
        valid_slugs = ", ".join([f"'{d.get('slug', '')}'" for d in defauts])
        prompt = f"""
Tu es un expert en découpe de verre industriel. Analyse la photographie ci-jointe et identifie le défaut technique parmi notre base de connaissances stricte.

Voici les défauts possibles dans la base (avec leur ID, titre et description) :
{defects_list_str}

Consignes d'analyse très essentielles :
- Si le bord du verre montre de GROSSES cassures franches, des fissures profondes, ou un gros morceau de verre arraché de façon brutale et irrégulière, la coupe a cédé sous le poids/la pression. Choix : "Trop de force".
- Si le bord présente un écaillage régulier, de multiples petites facettes successives ("dents de requin") le long de l'arête, avec un motif très répétitif, même sur plusieurs épaisseurs de verres empilés, c'est l'outil qui manque de qualité de coupe. Choix : "Defaut molette".
- Si tu vois seulement de la limaille, des petits grains luisants ou de très petites brisures libres sur la table, c'est de la poussière de coupe. Choix : "Paillettes".

Compare l'image à ces descriptions et déduis-en la cause racine.
Tu dois répondre UNIQUEMENT par l'ID du défaut retenu. AUCUNE phrase, AUCUN autre format. Les IDE authorisés sont EXCLUSIVEMENT : {valid_slugs}.
"""
        
        # Use gemini-1.5-flash as it is the original working model
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([prompt, img])
        
        try:
            suggested_text = response.text.strip().lower()
            raw_res = response.text
        except ValueError:
            # Caught if Gemini blocked the prompt due to safety ratings
            return jsonify({"error": "Erreur interne Gemini (bloqué par sécurité)"}), 500
            
        found_slug = None
        for d in defauts:
            slug_val = str(d.get('slug', ''))
            id_val = str(d.get('id', ''))
            titre_val = str(d.get('titre', ''))
            # Check if slug, id, or titre is in the response
            if slug_val.lower() in suggested_text or id_val.lower() in suggested_text or (titre_val and titre_val.lower() in suggested_text):
                found_slug = d['slug']
                break
                
        print(f"Gemini AI raw response: {response.text}", flush=True)
        print(f"Matched slug: {found_slug}", flush=True)
        
        if found_slug:
            return jsonify({"slug": found_slug, "raw_response": response.text})
        else:
            # Send back a 400 with the raw response so the frontend can display it
            return jsonify({"error": "Not matched", "raw_response": response.text}), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/transcribe-audio', methods=['POST'])
def transcribe_audio():
    """Transcribes audio using Gemini and returns structured text for the defect sheet."""
    data = request.json
    audio_data = data.get('audio_data')   # base64 string with data URI prefix
    context_name = data.get('context_name', 'un défaut mécanique de machine à couper le verre')

    if not audio_data:
        return jsonify({"error": "Missing audio_data"}), 400

    try:
        # Strip data URI prefix if present
        if "," in audio_data:
            header, audio_b64 = audio_data.split(",", 1)
            # Detect mime type from header
            mime_type = "audio/webm"
            if "mp4" in header or "m4a" in header:
                mime_type = "audio/mp4"
            elif "mp3" in header or "mpeg" in header:
                mime_type = "audio/mpeg"
            elif "wav" in header:
                mime_type = "audio/wav"
            elif "ogg" in header:
                mime_type = "audio/ogg"
        else:
            audio_b64 = audio_data
            mime_type = "audio/webm"

        audio_bytes = base64.b64decode(audio_b64)

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""
Tu es un assistant technique expert en machines de coupe industrielle.
Transcris fidèlement l'enregistrement audio ci-joint qui concerne: "{context_name}".
Puis reformate la transcription en fiche technique Markdown structurée avec les sections suivantes:

# Transcription – {context_name}

## 🔖 Résumé
(Résumé du problème en 2-3 phrases)

## 🔍 Causes identifiées
(Liste les causes citées)

## ✅ Actions correctives
(Liste les actions correctives mentionnées)

## ⚙️ Réglages conseillés
(Paramètres et réglages recommandés si mentionnés)

## 📝 Notes
(Toute autre information utile)

Réponds UNIQUEMENT avec le Markdown, sans explication supplémentaire.
"""

        # Upload audio as inline data
        audio_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": audio_b64
            }
        }

        response = model.generate_content([prompt, audio_part])
        transcription = response.text.strip()

        return jsonify({"transcription": transcription})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug-files')
def debug_files():
    tree = {}
    for root, dirs, files in os.walk(DATA_DIR):
        rel_path = os.path.relpath(root, DATA_DIR)
        tree[rel_path] = files
    return jsonify(tree)

@app.route('/api/expert/save', methods=['POST'])
def save_expert_data():
    data = request.json
    titre = data.get('titre')
    content = data.get('content', '')
    slug = data.get('slug')
    symptoms = data.get('symptoms', '').strip()
    photo_data = data.get('photo_data')   # base64 string
    audio_data = data.get('audio_data')   # base64 string
    
    if not titre or not content:
        return jsonify({"error": "Missing title or content"}), 400
        
    titre = titre.strip()
    folder_name = slug if slug else titre.strip()
    defaut_id = folder_name.lower().replace(" ", "-")
    
    # Inject/replace the Symptômes section at the top of the content
    import re as _re
    content = _re.sub(r'## Symptômes.*?(?=\n##|\Z)', '', content, flags=_re.DOTALL).strip()
    if symptoms:
        symptom_block = f"## Symptômes\n\n{symptoms}\n\n---\n\n"
    else:
        symptom_block = "## Symptômes\n\n*(à remplir)*\n\n---\n\n"
    content = symptom_block + content

    uploaded_photo_name = None
    uploaded_audio_name = None
    
    # Upload photo to Supabase Storage
    if photo_data and SUPABASE_URL and SUPABASE_KEY:
        try:
            if "," in photo_data:
                photo_data = photo_data.split(",")[1]
            photo_bytes = base64.b64decode(photo_data)
            photo_filename = f"{folder_name}/{folder_name}.jpg"
            import urllib.parse
            encoded_photo_filename = urllib.parse.quote(photo_filename)
            upload_url = f"{SUPABASE_URL}/storage/v1/object/medias/{encoded_photo_filename}"
            upload_headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "image/jpeg",
                "x-upsert": "true"
            }
            upload_res = requests.post(upload_url, headers=upload_headers, data=photo_bytes, verify=False)
            if upload_res.status_code in (200, 201):
                uploaded_photo_name = f"{folder_name}.jpg"
                print(f"Photo uploaded: {photo_filename}", flush=True)
            else:
                print(f"Photo upload error: {upload_res.text}", flush=True)
        except Exception as e:
            print(f"Photo upload exception: {e}", flush=True)

    # Upload audio to Supabase Storage
    if audio_data and SUPABASE_URL and SUPABASE_KEY:
        try:
            if "," in audio_data:
                audio_data = audio_data.split(",")[1]
            audio_bytes = base64.b64decode(audio_data)
            audio_filename = f"{folder_name}/{folder_name}.m4a"
            import urllib.parse
            encoded_audio_filename = urllib.parse.quote(audio_filename)
            upload_url = f"{SUPABASE_URL}/storage/v1/object/medias/{encoded_audio_filename}"
            upload_headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "audio/mp4",
                "x-upsert": "true"
            }
            upload_res = requests.post(upload_url, headers=upload_headers, data=audio_bytes, verify=False)
            if upload_res.status_code in (200, 201):
                uploaded_audio_name = f"{folder_name}.m4a"
                print(f"Audio uploaded: {audio_filename}", flush=True)
            else:
                print(f"Audio upload error: {upload_res.text}", flush=True)
        except Exception as e:
            print(f"Audio upload exception: {e}", flush=True)
    
    # Save to Supabase DB
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            row = {
                "id": defaut_id,
                "slug": folder_name,
                "titre": titre,
                "content": content,
                "date_transcription": "Aujourd'hui"
            }
            if uploaded_audio_name:
                row["audio"] = uploaded_audio_name
            # Upsert using resolution=merge-duplicates keeps existing columns intact
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/defauts", 
                headers=get_supabase_headers(), 
                json=row
            )
            if response.status_code not in (200, 201):
                print(f"Error saving to Supabase: {response.text}")
                return jsonify({"error": f"Failed to save to Supabase: {response.text}"}), 500
        except Exception as e:
            print(f"Error saving to Supabase: {e}")
            return jsonify({"error": f"Failed to save to Supabase: {e}"}), 500
    
    # Also save locally if possible
    try:
        folder_path = os.path.join(DATA_DIR, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        md_path = os.path.join(folder_path, f"{folder_name}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"---\ntitre: \"{folder_name}\"\ndate_transcription: \"Aujourd'hui\"\n---\n\n")
            f.write(content)
    except Exception as e:
        print(f"Could not write file locally: {e}")
        
    return jsonify({"success": True})
        
    return jsonify({"success": True})

# Support pour PWA manifest et icônes
@app.route('/manifest.json')
def serve_manifest():
    return jsonify({
        "name": "Coupe Verre",
        "short_name": "Coupe Verre",
        "start_url": ".",
        "display": "standalone",
        "background_color": "#0a0b10",
        "description": "Assistant technique de coupe"
    })

if __name__ == '__main__':
    # On autorise toutes les interfaces (0.0.0.0) pour l'accès mobile sur le même Wi-Fi
    app.run(debug=True, host='0.0.0.0', port=3000)
