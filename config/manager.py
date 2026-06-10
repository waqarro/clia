import json
import os
from typing import Optional

class ConfigManager:
    """Manages local configuration for CliChat."""
    
    def __init__(self, filepath: str = "clichat_config.json"):
        self.filepath = filepath
        self.config = {
            "username": "",
            "discovery_port": 50001,
            "tcp_port": 50002
        }
        self.load()

    def load(self) -> None:
        """Loads configuration from the JSON file if it exists."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config.update(data)
            except Exception as e:
                print(f"Error loading configuration: {e}")

    def save(self) -> None:
        """Saves current configuration to the JSON file."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving configuration: {e}")

    def get_username(self) -> str:
        return self.config.get("username", "")

    def set_username(self, username: str) -> None:
        self.config["username"] = username
        self.save()

    def get_discovery_port(self) -> int:
        return int(self.config.get("discovery_port", 50001))

    def get_tcp_port(self) -> int:
        return int(self.config.get("tcp_port", 50002))

    def set_tcp_port(self, port: int) -> None:
        self.config["tcp_port"] = port
        self.save()
