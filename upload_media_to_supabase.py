import os
import requests
import mimetypes
import urllib.parse
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY").strip() # Service Role Key

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'defauts')

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

def upload_media():
    if not os.path.exists(DATA_DIR):
        print("Data directory not found.")
        return

    for folder in os.listdir(DATA_DIR):
        folder_path = os.path.join(DATA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        
        for filename in os.listdir(folder_path):
            if filename.endswith('.md'):
                continue
            
            file_path = os.path.join(folder_path, filename)
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
                
            with open(file_path, "rb") as f:
                file_data = f.read()
            
            # encode only parts of the path, or just use requests to handle it if it complains.
            # but manually encoding is safer for Supabase Storage paths:
            encoded_folder = urllib.parse.quote(folder)
            encoded_filename = urllib.parse.quote(filename)
            
            url = f"{SUPABASE_URL}/storage/v1/object/medias/{encoded_folder}/{encoded_filename}"
            
            post_headers = headers.copy()
            post_headers["Content-Type"] = mime_type
            
            print(f"Uploading {folder}/{filename}...", flush=True)
            res = requests.post(url, headers=post_headers, data=file_data, verify=False)
            
            if res.status_code in (200, 201):
                print(f"Success: {folder}/{filename}", flush=True)
            elif res.status_code == 400 and 'Duplicate' in res.text:
                print(f"Already exists: {folder}/{filename}", flush=True)
            else:
                print(f"Error {res.status_code}: {res.text}", flush=True)

if __name__ == "__main__":
    upload_media()
