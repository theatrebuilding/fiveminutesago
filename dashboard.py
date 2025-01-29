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

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global references
gstreamer_process = None
config = load_config()

# Track node connection status
# We'll store the latest from gstreamer_pipeline.py here
node_status = {
    "A": False,
    "B": False,
    "C": False,
    "D": False
}

@app.route("/")
def index():
    # We pass the config and also the node_status to the template
    return render_template("index.html", config=config, node_status=node_status)

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
    # Start the pipeline as a separate process
    gstreamer_process = subprocess.Popen(["python3", "gstreamer_pipeline.py"])

@app.route("/restart_pipeline", methods=["POST"])
def restart_pipeline():
    threading.Thread(target=run_gstreamer).start()
    return jsonify({"status": "restarting"})

@socketio.on("connect")
def handle_connect():
    """When a client connects, immediately send them the config and the latest node status."""
    socketio.emit("config_updated", config)
    socketio.emit("status_update", node_status)

@socketio.on("update_status")
def handle_update_status(data):
    """
    gstreamer_pipeline.py will emit("update_status", {...}) with A/B/C/D statuses.
    We'll store that and re-broadcast to all clients as 'status_update'.
    """
    global node_status
    node_status = data
    print(f"📥 Received status update: {node_status}")  # Debug Print
    socketio.emit("status_update", node_status, broadcast=True)

if __name__ == "__main__":
    # Start the pipeline automatically
    threading.Thread(target=run_gstreamer).start()

    # Run Flask on port 7799
    # Access at http://<server-ip>:7799
    socketio.run(app, host="0.0.0.0", port=7799, debug=True)
