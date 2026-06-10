import json
import base64
from typing import Dict, Any, List, Optional
from datetime import datetime

# --- ENCRYPTION PLACEHOLDERS ---

def encrypt_payload(plain_text: str) -> str:
    """
    Placeholder encryption: Encodes payload using base64.
    In a production-ready application, replace this with E2EE
    (e.g., using python cryptography's Fernet AES or PyNaCl public-key encryption).
    """
    # Simply encode plain text to a base64 string for structural demonstration
    bytes_data = plain_text.encode('utf-8')
    encoded_bytes = base64.b64encode(bytes_data)
    return "[ENC]" + encoded_bytes.decode('utf-8')

def decrypt_payload(cipher_text: str) -> str:
    """
    Placeholder decryption: Decodes base64 payload.
    In a production-ready application, replace this with E2EE decryption.
    """
    if cipher_text.startswith("[ENC]"):
        try:
            encoded_bytes = cipher_text[5:].encode('utf-8')
            bytes_data = base64.b64decode(encoded_bytes)
            return bytes_data.decode('utf-8')
        except Exception:
            return "[Decryption Error]"
    return cipher_text

# --- PACKET GENERATORS ---

def create_discovery_packet(sender: str, ip: str, tcp_port: int, groups: List[str]) -> Dict[str, Any]:
    """Generates a discovery UDP broadcast packet."""
    return {
        "type": "discovery",
        "sender": sender,
        "ip": ip,
        "port": tcp_port,
        "groups": groups,
        "timestamp": datetime.now().isoformat()
    }

def create_discovery_response_packet(sender: str, ip: str, tcp_port: int, groups: List[str]) -> Dict[str, Any]:
    """Generates a discovery response UDP packet."""
    return {
        "type": "discovery_response",
        "sender": sender,
        "ip": ip,
        "port": tcp_port,
        "groups": groups,
        "timestamp": datetime.now().isoformat()
    }

def create_private_message_packet(sender: str, target: str, message: str, encrypt: bool = False) -> Dict[str, Any]:
    """Generates a private TCP message packet."""
    payload = encrypt_payload(message) if encrypt else message
    return {
        "type": "private_message",
        "sender": sender,
        "target": target,
        "message": payload,
        "encrypted": encrypt,
        "timestamp": datetime.now().isoformat()
    }

def create_group_message_packet(sender: str, target_group: str, message: str, encrypt: bool = False) -> Dict[str, Any]:
    """Generates a group TCP message packet."""
    payload = encrypt_payload(message) if encrypt else message
    return {
        "type": "group_message",
        "sender": sender,
        "target": target_group,
        "message": payload,
        "encrypted": encrypt,
        "timestamp": datetime.now().isoformat()
    }

def create_join_group_packet(sender: str, group_name: str) -> Dict[str, Any]:
    """Generates a packet informing peers we joined a group."""
    return {
        "type": "join_group",
        "sender": sender,
        "group": group_name,
        "timestamp": datetime.now().isoformat()
    }

def create_leave_group_packet(sender: str, group_name: str) -> Dict[str, Any]:
    """Generates a packet informing peers we left a group."""
    return {
        "type": "leave_group",
        "sender": sender,
        "group": group_name,
        "timestamp": datetime.now().isoformat()
    }

def create_status_update_packet(sender: str, status: str, ip: str, tcp_port: int, groups: List[str]) -> Dict[str, Any]:
    """Generates a status update packet (online/offline)."""
    return {
        "type": "status_update",
        "sender": sender,
        "status": status,
        "ip": ip,
        "port": tcp_port,
        "groups": groups,
        "timestamp": datetime.now().isoformat()
    }

def create_ping_packet(sender: str) -> Dict[str, Any]:
    """Generates a simple TCP keepalive ping packet."""
    return {
        "type": "ping",
        "sender": sender,
        "timestamp": datetime.now().isoformat()
    }

# --- PARSING & VALIDATION ---

def parse_packet(raw_data: str) -> Optional[Dict[str, Any]]:
    """Parses incoming raw JSON payload and returns the dictionary, or None if invalid."""
    try:
        packet = json.loads(raw_data)
        if isinstance(packet, dict) and "type" in packet and "sender" in packet:
            # If the packet contains a message and is flagged as encrypted, decrypt it.
            if packet.get("encrypted") and "message" in packet:
                packet["message"] = decrypt_payload(packet["message"])
            return packet
    except Exception:
        pass
    return None

def serialize_packet(packet: Dict[str, Any]) -> str:
    """Serializes a packet dict to a JSON string terminated by a newline for TCP stream framing."""
    return json.dumps(packet) + "\n"
