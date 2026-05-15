import os
import sys
import yaml


def get_config_path():
    override = os.getenv("CONFIG_PATH")
    if override and override.strip():
        return os.path.abspath(os.path.expanduser(override.strip()))

    dir_path = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(dir_path, "config.yaml")


def load_config():
    """
    Loads config from CONFIG_PATH when set, otherwise from the local
    production/config.yaml next to this file.
    Returns a Python dictionary with the config contents.
    """
    config_path = get_config_path()

    if not os.path.isfile(config_path):
        print(f"ERROR: Could not find config file at {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        return yaml.safe_load(f)
