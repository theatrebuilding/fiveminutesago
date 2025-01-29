from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import yaml
import subprocess
import threading

# Load initial config
CONFIG_FILE = "config.yaml"
def load_config():
    with open(CONFIG_FILE, "r") as file:
        return yaml.safe_load(file)

# Flask app setup
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global process reference
gstreamer_process = None
config = load_config()

@app.route("/")
def index():
    return render_template("index.html", config=config)

@app.route("/update_config", methods=["POST"])
def update_config():
    global config
    data = request.json
    config.update(data)  # Merge new settings
    with open(CONFIG_FILE, "w") as file:
        yaml.safe_dump(config, file)

    socketio.emit("config_updated", config)
    return jsonify({"status": "success", "new_config": config})

def run_gstreamer():
    global gstreamer_process
    if gstreamer_process:
        gstreamer_process.terminate()
    gstreamer_process = subprocess.Popen(["python3", "gstreamer_pipeline.py"])

@app.route("/restart_pipeline", methods=["POST"])
def restart_pipeline():
    threading.Thread(target=run_gstreamer).start()
    return jsonify({"status": "restarting"})

@socketio.on("connect")
def handle_connect():
    socketio.emit("config_updated", config)

if __name__ == "__main__":
    threading.Thread(target=run_gstreamer).start()
    socketio.run(app, host="0.0.0.0", port=7799, debug=True)
