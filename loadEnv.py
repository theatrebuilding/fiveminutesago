import json
def load_env(env_path):
    with open(env_path, "r") as f:
        return json.load(f)