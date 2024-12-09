import json
import base64
import requests
from loadEnv import load_env

def update_ngrok_url(ngrok_url, env_path):
    # Load the environment variables from JSON file
    env = load_env(env_path)
    GITHUB_TOKEN = env.get("GITHUB_TOKEN")
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not found in environment file.")

    GITHUB_REPO = "theatrebuilding/ngrokurl"
    FILE_PATH = "config.json"
    jsonURL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Attempt to fetch existing file from the repo
    existing_content = {}
    sha = None

    response = requests.get(jsonURL, headers=headers)
    if response.status_code == 200:
        data = response.json()
        sha = data["sha"]
        content_str = base64.b64decode(data["content"]).decode("utf-8")
        existing_content = json.loads(content_str)
    elif response.status_code == 404:
        # create the file if it doesn't exist
        existing_content = {}
    else:
        # Another unexpected status code
        print(f"Unexpected status code: {response.status_code}")
        print(response.text)
        return False

    # Update the ngrok_url field
    existing_content["ngrok_url"] = ngrok_url

    # Encode updated content
    updated_content = json.dumps(existing_content, indent=2)
    updated_content_base64 = base64.b64encode(updated_content.encode("utf-8")).decode("utf-8")

    body_data = {
        "message": "Set ngrok URL in config.json",
        "content": updated_content_base64
    }
    if sha:
        body_data["sha"] = sha

    put_response = requests.put(jsonURL, headers=headers, data=json.dumps(body_data))
    if put_response.status_code in [200, 201]:
        print("Ngrok URL updated and pushed to repo successfully.")
        return True
    else:
        print(f"Error updating GitHub: {put_response.status_code}")
        print(put_response.text)
        return False
