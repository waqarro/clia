# CliChat — Local Peer-to-Peer CLI Messenger

CliChat is a fully local, peer-to-peer (P2P) terminal chat application written in Python. It does not require any central server, cloud database, or internet connection. Every instance acts as both a TCP server (to receive messages) and a TCP client (to send messages), utilizing UDP broadcasts to automatically discover nearby users on the same Wi-Fi/LAN subnet.

---

## Folder Structure

```
clichat/
│
├── main.py               # Application entry point & coordination
├── requirements.txt      # Python dependencies (prompt_toolkit)
├── config/
│   ├── __init__.py
│   └── manager.py        # Config loader/saver
├── storage/
│   ├── __init__.py
│   └── db.py             # SQLite message/peer/group storage
├── protocol/
│   ├── __init__.py
│   └── packets.py        # JSON packet serializer/deserializer & format schemas
├── discovery/
│   ├── __init__.py
│   └── udp.py            # UDP broadcast listener & periodic announcer
├── networking/
│   ├── __init__.py
│   └── tcp.py            # TCP message receiver & client relay
├── ui/
│   ├── __init__.py
│   └── terminal.py       # Dual-pane terminal UI & keyboard command loop
└── utils/
    ├── __init__.py
    └── helpers.py        # Username validators, message sanitizers, IP resolvers
```

---

## Setup Instructions

Ensure you have **Python 3.8+** installed.

### 1. Set up a virtual environment (Recommended)
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

---

## Example Usage

### Running on the same computer (For local testing)

To test CliChat locally, you can spin up multiple terminal sessions on the same machine. Each instance uses a separate database and configuration file automatically when passed a specific username as an argument.

1. **Terminal 1**: Run the first instance:
   ```bash
   python main.py Alice
   ```
2. **Terminal 2**: Run the second instance:
   ```bash
   python main.py Bob
   ```
3. **Terminal 3**: (Optional) Run a third instance:
   ```bash
   python main.py Charlie
   ```

### Running on different computers (On the same Wi-Fi/LAN)

If running across different physical machines on the same local network:
1. Ensure both computers are connected to the same router / Wi-Fi subnet.
2. Run:
   ```bash
   python main.py
   ```
3. If it is your first time running, the app will ask you to enter your username.
4. Once running, they will automatically broadcast their existence, find each other, and display their names in the left-hand panel.

---

## Chatting & CLI Commands

Once inside the application, you can type messages directly and press **Enter** to send them, or use slash commands.

### Navigation / Selecting Chat Targets
- **/msg <username>**
  Selects a user from the sidebar to chat with. Once selected, all subsequent typed text is sent to that peer.
  *Example*: `/msg Bob` followed by `hello Bob`
- **/peer add <ip_address>:[port]**
  Manually links to a remote peer outside your local network (e.g., across the internet using a virtual LAN like Tailscale, or a direct public IP address). It performs a TCP discovery handshake to sync peer databases.
  *Example*: `/peer add 100.80.90.12` or `/peer add 192.168.1.150:50003`
- **/group join <group_name>**
  Joins (and creates, if new) a local group chat. Updates your active window to that group.
  *Example*: `/group join dev_team` followed by `anyone online?`
- **/group create <group_name>**
  Creates a group and updates your active window.
- **/group leave <group_name>**
  Leaves a group and stops listening/relaying messages for it.

### Listing Users & Groups
- **/users**
  Refreshes and prints all discovered peers on the LAN inside the system logs window.
- **/groups**
  Lists all group names you are currently joined to.

### System Utilities
- **/help**
  Displays the manual containing all available CLI commands.
- **/clear**
  Deletes message history persistently for the current selected conversation (or clears the logs if no conversation is active).
- **/exit**
  Broadcasts an offline notification packet to the LAN, shuts down TCP servers, and exits the application cleanly. You can also press **Ctrl+C** or **Ctrl+D** to exit.
- **PageUp / PageDown**
  Scrolls through long message logs in the active conversation panel.
