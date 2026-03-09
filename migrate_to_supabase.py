import os
import frontmatter
from dotenv import load_dotenv
import requests

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'defauts')

def get_defauts():
    results = []
    if not os.path.exists(DATA_DIR):
        print("No data dir")
        return results

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
            
            audio = next((f for f in files if f.endswith('.m4a')), None)
            
            # create dictionary for row
            row = {
                "id": folder.lower().replace(" ", "-"),
                "slug": folder,
                "titre": post.metadata.get('titre', folder),
                "content": post.content,
                "date_transcription": post.metadata.get('date_transcription', ''),
                "audio": audio if audio else ''
            }
            results.append(row)
    return results

if __name__ == "__main__":
    defauts = get_defauts()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    print(f"Migrating {len(defauts)} defauts to Supabase...", flush=True)
    for d in defauts:
        try:
            print(f"Upserting {d['id']}...", flush=True)
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/defauts?on_conflict=id", 
                headers=headers, 
                json=d,
                timeout=10,
                verify=False
            )
            if response.status_code in (200, 201):
                print(f"Success: {d['id']}", flush=True)
            else:
                print(f"Error upserting {d['id']}: {response.text}", flush=True)
        except Exception as e:
            print(f"Error upserting {d['id']}: {e}", flush=True)
