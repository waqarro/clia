import sys
import asyncio
from config.manager import ConfigManager
from storage.db import DatabaseManager
from utils.helpers import get_local_ip, validate_username
from networking.tcp import TcpService
from discovery.udp import DiscoveryService
from ui.terminal import TerminalTui

async def async_main():
    # 1. Parse arguments or prompt for username
    username = None
    config_path = "clichat_config.json"
    
    if len(sys.argv) > 1:
        username = sys.argv[1].strip()
        if not validate_username(username):
            print("Error: Username must be 3-15 alphanumeric characters or underscores.")
            sys.exit(1)
        # Use isolated config and database for custom user instances to enable multi-instance local runs
        config_path = f"clichat_config_{username}.json"
        
    config_mgr = ConfigManager(config_path)
    
    if username:
        config_mgr.set_username(username)
    else:
        username = config_mgr.get_username()
        if not username:
            # Prompt username interactively on first launch
            print("=========================================")
            print("   CLICHAT — Local P2P CLI Messenger     ")
            print("=========================================")
            while True:
                try:
                    input_name = input("Enter your username (3-15 chars, A-Z, 0-9, _): ").strip()
                    if validate_username(input_name):
                        username = input_name
                        break
                    print("Invalid username. Please try again.")
                except (KeyboardInterrupt, EOFError):
                    print("\nGoodbye!")
                    sys.exit(0)
            config_mgr.set_username(username)

    # Isolated database file per user
    db_path = f"clichat_{username}.db"
    db_mgr = DatabaseManager(db_path)
    
    # 2. Get local network IP
    local_ip = get_local_ip()
    
    # 3. Initialize TCP Service (with placeholder UI callback wires)
    tcp_service = TcpService(username, db_mgr)
    
    # Placeholder for TUI reference to resolve callbacks
    tui = None
    
    def on_message(packet):
        if tui:
            tui.on_message_received(packet)
            
    def on_status():
        if tui:
            tui.on_peer_status_changed()
            
    tcp_service.ui_msg_callback = on_message
    tcp_service.ui_status_callback = on_status
    
    # 4. Start TCP Server (will fallback to next ports if busy)
    listening_port = await tcp_service.start(config_mgr.get_tcp_port())
    config_mgr.set_tcp_port(listening_port)
    
    # 5. Initialize UDP Discovery Service
    discovery_service = DiscoveryService(
        username=username,
        local_ip=local_ip,
        tcp_port=listening_port,
        discovery_port=config_mgr.get_discovery_port(),
        db_manager=db_mgr,
        ui_callback=on_status
    )
    
    # Connect services to prevent circular initialization issues
    tcp_service.set_discovery_service(discovery_service)
    
    # 6. Start UDP Broadcast Discovery
    await discovery_service.start()
    
    # 7. Start TUI Interface
    tui = TerminalTui(
        username=username,
        local_ip=local_ip,
        tcp_port=listening_port,
        discovery_port=config_mgr.get_discovery_port(),
        db_manager=db_mgr,
        tcp_service=tcp_service,
        discovery_service=discovery_service
    )
    
    # Log starting message inside TUI system logs
    tui.add_system_log(f"Successfully joined local chat as '{username}'.")
    tui.add_system_log(f"Listening for TCP messages on port {listening_port}.")
    tui.add_system_log(f"Broadcasting presence on UDP discovery port {config_mgr.get_discovery_port()}.")
    
    # Run TUI loop
    await tui.run()

def main():
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"CliChat crashed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
