import socket
import re

def get_local_ip() -> str:
    """
    Finds the primary local IP address of this device on the active network interface.
    Connects to a dummy external address to force the OS to pick the correct route interface.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Using a non-routable/dummy IP to trigger interface selection
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        # Fallback to localhost if no network interface is active
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def validate_username(username: str) -> bool:
    """
    Validates that a username is between 3 and 15 characters,
    and only contains alphanumeric characters and underscores.
    """
    if not username:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_]{3,15}$", username))

def sanitize_message(message: str) -> str:
    """
    Sanitizes message input by removing control characters, NULL bytes,
    and trimming surrounding whitespace.
    """
    if not message:
        return ""
    # Strip NULL bytes and control characters, keeping standard printables and newlines
    cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', message)
    return cleaned.strip()
