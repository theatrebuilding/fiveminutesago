import os
import sys
import yaml

def load_config():
    """
    Loads 'config.yaml' from the *same* directory this file is in.
    Returns a Python dictionary with the config contents.
    """
    # Get the directory where *this* file (config_loader.py) is located
    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(dir_path, "config.yaml")

    if not os.path.isfile(config_path):
        print(f"ERROR: Could not find config file at {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        return yaml.safe_load(f)
