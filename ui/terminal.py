import asyncio
import os
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.completion import Completer, Completion

from storage.db import DatabaseManager
from networking.tcp import TcpService
from utils.helpers import validate_username, sanitize_message

# --- MODERN STYLING SHEET ---
tui_style = Style.from_dict({
    'header': 'bg:#111111 #00ffcc bold',
    'sidebar': 'bg:#181818 #a0a0a0',
    'sidebar.title': '#00ffcc bold',
    'sidebar.online': '#00ff00 bold',
    'sidebar.offline': '#555555 italic',
    'sidebar.group': '#ff00ff bold',
    'sidebar.divider': '#333333',
    'chat': 'bg:#202020 #dddddd',
    'chat.header': 'bg:#181818 #00ffcc bold',
    'chat.time': '#555555',
    'chat.sender.you': '#00ffcc bold',
    'chat.sender.peer': '#ffff00 bold',
    'chat.system': '#ffaa00 italic',
    'input': 'bg:#151515 #ffffff',
    'input.prompt': '#00ffcc bold',
})


class CliChatCompleter(Completer):
    """Dynamic autocomplete completer for CliChat commands, online usernames, and joined groups."""

    def __init__(self, tui: 'TerminalTui'):
        self.tui = tui

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        
        # Only trigger completion for command chains starting with "/"
        if not text.startswith("/"):
            return
            
        words = text.split()
        if not words:
            return
            
        # Case 1: Autocomplete the root command (e.g. "/m" -> "/msg")
        if len(words) == 1 and not text.endswith(" "):
            cmd_typed = words[0]
            commands = [
                "/help", "/users", "/msg", 
                "/peer", "/group", "/groups", "/clear", "/exit"
            ]
            for cmd in commands:
                if cmd.startswith(cmd_typed):
                    yield Completion(cmd, start_position=-len(cmd_typed))
                    
        # Case 2: Autocomplete command-specific arguments
        elif len(words) >= 2 or (len(words) == 1 and text.endswith(" ")):
            cmd = words[0].lower()
            
            # /msg <username>
            if cmd == "/msg":
                # Find which username segment we are typing
                typed_arg = words[1] if len(words) >= 2 and not (len(words) == 1 and text.endswith(" ")) else ""
                if len(words) > 2 or (len(words) == 2 and text.endswith(" ")):
                    return
                
                peers = self.tui.db_manager.get_all_peers()
                for p in peers:
                    name = p['username']
                    if name.startswith(typed_arg) and name != self.tui.username:
                        yield Completion(name, start_position=-len(typed_arg))
                        
            # /group [create|join|leave] <group_name>
            elif cmd == "/group":
                subcmd = words[1].lower() if len(words) >= 2 else ""
                
                # Autocomplete subcommands: create, join, leave
                if len(words) == 1 or (len(words) == 2 and not text.endswith(" ")):
                    subcmds = ["create", "join", "leave"]
                    for sc in subcmds:
                        if sc.startswith(subcmd):
                            yield Completion(sc, start_position=-len(subcmd))
                # Autocomplete joined group names
                elif len(words) >= 2:
                    subcmd = words[1].lower()
                    if subcmd in ("join", "leave", "create"):
                        typed_arg = words[2] if len(words) >= 3 and not (len(words) == 2 and text.endswith(" ")) else ""
                        if len(words) > 3 or (len(words) == 3 and text.endswith(" ")):
                            return
                        
                        groups = self.tui.db_manager.get_joined_groups()
                        for g in groups:
                            if g.startswith(typed_arg):
                                yield Completion(g, start_position=-len(typed_arg))
                                
            # /peer add <ip>
            elif cmd == "/peer":
                subcmd = words[1].lower() if len(words) >= 2 else ""
                if len(words) == 1 or (len(words) == 2 and not text.endswith(" ")):
                    subcmds = ["add"]
                    for sc in subcmds:
                        if sc.startswith(subcmd):
                            yield Completion(sc, start_position=-len(subcmd))


class TerminalTui:
    """Manages the interactive terminal chat UI using prompt_toolkit."""

    def __init__(
        self,
        username: str,
        local_ip: str,
        tcp_port: int,
        discovery_port: int,
        db_manager: DatabaseManager,
        tcp_service: TcpService,
        discovery_service: Any
    ):
        self.username = username
        self.local_ip = local_ip
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.db_manager = db_manager
        self.tcp_service = tcp_service
        self.discovery_service = discovery_service

        # Chat states
        self.active_target = None  # Peer username or group name
        self.active_type = None    # 'private' or 'group'
        
        # UI controls
        self.messages_list: List[List[Tuple[str, str]]] = []
        self.scroll_offset = 0     # Number of lines scrolled up from bottom
        
        # System status messages displayed inside chat area
        self.system_logs: List[str] = [
            "Welcome to CliChat! Type /help to see a list of commands."
        ]

        # UI elements with dynamic prompt and auto-completer
        self.input_field = TextArea(
            height=1,
            prompt=self.get_prompt_text,
            style='class:input',
            multiline=False,
            wrap_lines=False,
            completer=CliChatCompleter(self)
        )
        
        self.app = None

    def add_system_log(self, text: str) -> None:
        """Adds a local TUI event notification."""
        self.system_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self.reset_scroll()
        self.refresh()

    def reset_scroll(self) -> None:
        self.scroll_offset = 0

    def refresh(self) -> None:
        """Forces the TUI to invalidate and redraw the interface."""
        if self.app:
            self.app.invalidate()

    # --- FORMATTED TEXT GENERATORS ---

    def get_prompt_text(self) -> List[Tuple[str, str]]:
        """Generates dynamic input prompt showing active chat destination."""
        if not self.active_target:
            return [('class:input.prompt', "[Select target (use mouse or /msg)] > ")]
        elif self.active_type == "group":
            return [('class:input.prompt', f"[You ➜ #{self.active_target}] > ")]
        else:
            return [('class:input.prompt', f"[You ➜ {self.active_target}] > ")]

    def get_header_text(self) -> List[Tuple[str, str]]:
        return [
            ('class:header', f" █ CLICHAT █   User: {self.username} | IP: {self.local_ip}:{self.tcp_port} | Discovery Port: {self.discovery_port} ")
        ]

    def get_chat_header_text(self) -> List[Tuple[str, str]]:
        if not self.active_target:
            return [('class:chat.header', " 💬 No active conversation. Click a peer on the left or type /msg <user>")]
        target_display = f"Group: #{self.active_target}" if self.active_type == "group" else f"User: {self.active_target}"
        return [('class:chat.header', f" 💬 Conversation | {target_display}")]

    # --- MOUSE ACTIONS ---

    def make_peer_click_handler(self, peer_name: str) -> Callable[[MouseEvent], None]:
        """Returns click handler to switch chat view to a peer."""
        def handler(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self.active_target = peer_name
                self.active_type = "private"
                self.reset_scroll()
                self.add_system_log(f"Switched chat window to user: {peer_name}")
                self.refresh()
        return handler

    def make_group_click_handler(self, group_name: str) -> Callable[[MouseEvent], None]:
        """Returns click handler to switch chat view to a group."""
        def handler(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self.active_target = group_name
                self.active_type = "group"
                self.reset_scroll()
                self.add_system_log(f"Switched chat window to group: #{group_name}")
                self.refresh()
        return handler

    def make_chat_scroll_handler(self) -> Callable[[MouseEvent], None]:
        """Returns mouse handler to scroll the chat history via mouse wheel."""
        def handler(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                fragments = self.get_chat_history_text()
                line_count = sum(1 for _, text, *_ in fragments if '\n' in text)
                self.scroll_offset = min(line_count - 5, self.scroll_offset + 5)
                self.refresh()
            elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self.scroll_offset = max(0, self.scroll_offset - 5)
                self.refresh()
        return handler

    def get_sidebar_text(self) -> List[Tuple[str, str]]:
        text = []
        text.append(('', '\n'))
        text.append(('class:sidebar.title', ' 💻 ONLINE PEERS\n'))
        text.append(('class:sidebar.divider', ' ─────────────────────\n'))
        
        peers = self.db_manager.get_all_peers()
        online_peers = [p for p in peers if p['status'] == 'online']
        offline_peers = [p for p in peers if p['status'] != 'online']
        
        if not online_peers:
            text.append(('class:sidebar.offline', '  (No peers active)\n'))
        else:
            for p in online_peers:
                bullet = '● '
                name = p['username']
                is_active = (self.active_target == name and self.active_type == 'private')
                style = 'underline class:sidebar.online' if is_active else 'class:sidebar.online'
                
                # Bind mouse click action
                handler = self.make_peer_click_handler(name)
                text.append((style, f"  {bullet}{name}", handler))
                
                # If there are joined groups in common, list them next to peer name in muted style
                peer_groups = self.discovery_service.peer_groups.get(name, set()) if self.discovery_service else set()
                if peer_groups:
                    text.append(('class:sidebar.offline', f" ({','.join(peer_groups)})", handler))
                text.append(('', '\n'))
                
        text.append(('', '\n'))
        text.append(('class:sidebar.title', ' 💬 JOINED GROUPS\n'))
        text.append(('class:sidebar.divider', ' ─────────────────────\n'))
        
        groups = self.db_manager.get_joined_groups()
        if not groups:
            text.append(('class:sidebar.offline', '  (No groups joined)\n'))
        else:
            for g in groups:
                bullet = '# '
                is_active = (self.active_target == g and self.active_type == 'group')
                style = 'underline class:sidebar.group' if is_active else 'class:sidebar.group'
                
                # Bind mouse click action
                handler = self.make_group_click_handler(g)
                text.append((style, f"  {bullet}{g}\n", handler))
                
        # If there are offline peers, display them at the bottom
        if offline_peers:
            text.append(('', '\n'))
            text.append(('class:sidebar.title', ' 💤 OFFLINE PEERS\n'))
            text.append(('class:sidebar.divider', ' ─────────────────────\n'))
            for p in offline_peers:
                bullet = '○ '
                name = p['username']
                is_active = (self.active_target == name and self.active_type == 'private')
                style = 'underline class:sidebar.offline' if is_active else 'class:sidebar.offline'
                
                # Bind mouse click action
                handler = self.make_peer_click_handler(name)
                text.append((style, f"  {bullet}{name}\n", handler))

        return text

    def get_chat_history_text(self) -> List[Tuple[str, str]]:
        fragments = []
        scroll_handler = self.make_chat_scroll_handler()
        
        # Display onboarding welcome dashboard if no conversation is active
        if not self.active_target:
            fragments.append(('class:sidebar.title', '\n    █▀▀ █   █ █▀▀ █ █▀█ █▀█ ▀█▀\n    █▄▄ █▄▄ █ █▄▄ █▀█ █▄█ █_█  █ \n\n', scroll_handler))
            fragments.append(('class:chat.header', '  🚀 WELCOME TO CLICHAT — PEER-TO-PEER MESSENGER\n\n', scroll_handler))
            fragments.append(('class:chat.system', f"  • Current Session: {self.username} on IP {self.local_ip}\n", scroll_handler))
            fragments.append(('class:chat.system', f"  • Active TCP Server Port: {self.tcp_port}\n", scroll_handler))
            fragments.append(('class:chat.system', f"  • UDP Discovery Port: {self.discovery_port}\n\n", scroll_handler))
            fragments.append(('class:sidebar.title', '  📋 QUICK START INSTRUCTIONS:\n', scroll_handler))
            fragments.append(('class:sidebar.divider', '  ──────────────────────────────────────────────\n', scroll_handler))
            fragments.append(('class:chat', '  1. Discover Peers: Discovered peers will automatically appear in the sidebar on the left.\n', scroll_handler))
            fragments.append(('class:chat', '  2. Select Chat: Click on a peer name in the sidebar, or type: /msg <username>\n', scroll_handler))
            fragments.append(('class:chat', '  3. Group Chats: Join or create groups: /group join <group_name>\n', scroll_handler))
            fragments.append(('class:chat', '  4. Autocomplete: Type / and press Tab to view and autocomplete commands/peers!\n\n', scroll_handler))
            fragments.append(('class:sidebar.title', '  📜 RECENT NOTIFICATIONS:\n', scroll_handler))
            fragments.append(('class:sidebar.divider', '  ──────────────────────────────────────────────\n', scroll_handler))
            for log in self.system_logs[-6:]:
                fragments.append(('class:chat.system', f"   * {log}\n", scroll_handler))
            return fragments

        # Fetch messages
        messages = self.db_manager.get_chat_history(self.username, self.active_target, self.active_type)
        
        # Render message lines
        lines = []
        for msg in messages:
            line = []
            try:
                dt = datetime.fromisoformat(msg['timestamp'])
                time_str = dt.strftime('%H:%M:%S')
            except Exception:
                time_str = msg['timestamp'][:19]
            
            line.append(('class:chat.time', f"[{time_str}] "))
            if msg['sender'] == self.username:
                line.append(('class:chat.sender.you', "You: "))
            else:
                line.append(('class:chat.sender.peer', f"{msg['sender']}: "))
            
            line.append(('', msg['content']))
            lines.append(line)

        if not lines:
            fragments.append(('', '\n   No message history with this contact.\n   Type your message below and press Enter to start chatting!\n', scroll_handler))
            return fragments

        # Create flattened tokens with newlines, attaching scroll handlers
        flat_fragments = []
        for line in lines:
            for style, text in line:
                flat_fragments.append((style, text, scroll_handler))
            flat_fragments.append(('', '\n', scroll_handler))
            
        return flat_fragments

    def get_cursor_position(self) -> Optional[Point]:
        """
        Dynamically calculates the cursor position to simulate scrolling.
        Points to the bottom line minus the scroll offset.
        """
        fragments = self.get_chat_history_text()
        line_count = sum(text.count('\n') for _, text, *_ in fragments)
        
        target_line = max(0, line_count - 1 - self.scroll_offset)
        return Point(x=0, y=target_line)

    # --- COMMAND PROCESSING ---

    async def handle_input(self) -> None:
        """Processes text entered in the input field."""
        text = self.input_field.text.strip()
        if not text:
            return
            
        self.input_field.text = ""
        
        # Check for commands
        if text.startswith("/"):
            await self.process_command(text)
        else:
            # Regular message sending
            if not self.active_target:
                self.add_system_log("No conversation selected. Use /msg <username> or /group join <group_name> first.")
                return
                
            if self.active_type == "private":
                sanitized = sanitize_message(text)
                success = await self.tcp_service.send_private_message(self.active_target, sanitized)
                if success:
                    self.reset_scroll()
                    self.refresh()
                else:
                    self.add_system_log(f"Error: Disconnected. Could not reach user '{self.active_target}'.")
            elif self.active_type == "group":
                sanitized = sanitize_message(text)
                sent_count = await self.tcp_service.send_group_message(self.active_target, sanitized)
                self.reset_scroll()
                self.refresh()

    async def process_command(self, text: str) -> None:
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd == "/help":
            self.add_system_log(
                "Available Commands:\n"
                "   /help                         - Show this help list\n"
                "   /users                        - List all discovered online users\n"
                "   /msg <username>               - Start a private chat window with a user\n"
                "   /peer add <ip>:[port]         - Connect directly to a remote peer via IP\n"
                "   /group create <group_name>    - Create and join a new group\n"
                "   /group join <group_name>      - Join an existing group\n"
                "   /group leave <group_name>     - Leave a group\n"
                "   /groups                       - List all groups you are a member of\n"
                "   /clear                        - Clear message log history for the current view\n"
                "   /exit                         - Exit CliChat safely"
            )
            
        elif cmd == "/users":
            peers = self.db_manager.get_all_peers()
            online = [p['username'] for p in peers if p['status'] == 'online']
            self.add_system_log(f"Online Users ({len(online)}): {', '.join(online) if online else 'None'}")
            
        elif cmd == "/msg":
            if not args:
                self.add_system_log("Usage: /msg <username>")
                return
            target = args[0]
            if target == self.username:
                self.add_system_log("You cannot start a private chat with yourself.")
                return
            
            # Check if peer is known, if not search or insert
            peer = self.db_manager.get_peer(target)
            if not peer:
                self.add_system_log(f"User '{target}' has not been discovered on LAN yet. If they exist, wait for discovery.")
            
            self.active_target = target
            self.active_type = "private"
            self.reset_scroll()
            self.add_system_log(f"Switched chat window to user: {target}")
            self.refresh()
            
        elif cmd == "/group":
            if len(args) < 2:
                self.add_system_log("Usage: /group [create|join|leave] <group_name>")
                return
                
            action = args[0].lower()
            group_name = args[1]
            
            # Basic validation
            if not validate_username(group_name):
                self.add_system_log("Invalid group name. Must be 3-15 chars, alphanumeric or underscores.")
                return
                
            if action == "create":
                self.db_manager.create_or_join_group(group_name)
                await self.discovery_service.notify_group_action("join", group_name)
                self.active_target = group_name
                self.active_type = "group"
                self.reset_scroll()
                self.add_system_log(f"Created and joined group: #{group_name}")
                self.refresh()
                
            elif action == "join":
                self.db_manager.create_or_join_group(group_name)
                await self.discovery_service.notify_group_action("join", group_name)
                self.active_target = group_name
                self.active_type = "group"
                self.reset_scroll()
                self.add_system_log(f"Joined group: #{group_name}")
                self.refresh()
                
            elif action == "leave":
                if self.db_manager.is_group_joined(group_name):
                    self.db_manager.leave_group(group_name)
                    await self.discovery_service.notify_group_action("leave", group_name)
                    if self.active_target == group_name:
                        self.active_target = None
                        self.active_type = None
                    self.add_system_log(f"Left group: #{group_name}")
                    self.refresh()
                else:
                    self.add_system_log(f"You are not a member of group: #{group_name}")
            else:
                self.add_system_log("Unknown group action. Use /group [create|join|leave] <group_name>")
                
        elif cmd == "/groups":
            groups = self.db_manager.get_joined_groups()
            self.add_system_log(f"Joined Groups: {', '.join([f'#{g}' for g in groups]) if groups else 'None'}")
            
        elif cmd == "/clear":
            if self.active_target:
                self.db_manager.clear_chat_history(self.username, self.active_target, self.active_type)
                self.add_system_log(f"Cleared chat history with '{self.active_target}'.")
            else:
                self.system_logs = ["System logs cleared."]
            self.reset_scroll()
            self.refresh()
            
        elif cmd == "/peer":
            if len(args) < 2 or args[0].lower() != "add":
                self.add_system_log("Usage: /peer add <ip>:[port] or /peer add <ip>")
                return
            
            target_ip_port = args[1]
            if ":" in target_ip_port:
                try:
                    ip, port_str = target_ip_port.split(":")
                    port = int(port_str)
                except Exception:
                    self.add_system_log("Error: Invalid IP:port format. Example: 192.168.1.50:50002")
                    return
            else:
                ip = target_ip_port
                port = 50002 # Default TCP port
                
            self.add_system_log(f"Attempting direct P2P connection to {ip}:{port}...")
            asyncio.create_task(self.direct_connect_peer(ip, port))

        elif cmd == "/exit":
            self.add_system_log("Exiting CliChat...")
            await self.shutdown()
            
        else:
            self.add_system_log(f"Unknown command '{cmd}'. Type /help for options.")

    # --- EVENTS ---

    def on_message_received(self, packet: dict) -> None:
        """Called by the TCP server when a message is received."""
        sender = packet.get("sender")
        msg_type = packet.get("type")
        target = packet.get("target")
        
        if msg_type == "private_message" and self.active_target == sender and self.active_type == "private":
            self.reset_scroll()
        elif msg_type == "group_message" and self.active_target == target and self.active_type == "group":
            self.reset_scroll()
            
        # Auto insert a inline system notification if the sender just popped up
        self.refresh()

    def on_peer_status_changed(self) -> None:
        """Called when a peer goes online/offline/updates group membership."""
        self.refresh()

    async def direct_connect_peer(self, ip: str, port: int) -> None:
        """Sends a direct TCP discovery request to a remote peer to link networks."""
        from protocol.packets import create_discovery_packet, serialize_packet, parse_packet
        
        packet = create_discovery_packet(
            self.username,
            self.local_ip,
            self.tcp_port,
            self.db_manager.get_joined_groups()
        )
        data = serialize_packet(packet).encode('utf-8')
        
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5.0
            )
            writer.write(data)
            await writer.drain()
            
            # Wait for their reply discovery_response over TCP
            resp = await asyncio.wait_for(reader.readline(), timeout=5.0)
            writer.close()
            await writer.wait_closed()
            
            if resp:
                resp_packet = parse_packet(resp.decode('utf-8').strip())
                if resp_packet and resp_packet.get("type") == "discovery_response":
                    sender = resp_packet.get("sender")
                    groups = resp_packet.get("groups", [])
                    
                    self.db_manager.save_peer(sender, ip, port, "online")
                    self.discovery_service.update_peer_groups(sender, groups)
                    
                    self.add_system_log(f"Direct connection established! Discovered '{sender}' at {ip}:{port}")
                    self.refresh()
                    return
            
            self.add_system_log(f"Direct connection to {ip}:{port} failed: Peer sent invalid response.")
        except Exception:
            self.add_system_log(f"Direct connection to {ip}:{port} failed: Connection timed out or refused.")

    # --- TUI LIFECYCLE ---

    async def run(self) -> None:
        """Builds and starts the main TUI application event loop."""
        # Setup layouts
        header_window = Window(
            height=1,
            content=FormattedTextControl(self.get_header_text),
            style='class:header',
            align=WindowAlign.CENTER
        )
        
        sidebar_window = Window(
            content=FormattedTextControl(self.get_sidebar_text),
            style='class:sidebar',
            width=26
        )
        
        chat_header_window = Window(
            height=1,
            content=FormattedTextControl(self.get_chat_header_text),
            style='class:chat.header'
        )
        
        chat_history_window = Window(
            content=FormattedTextControl(
                self.get_chat_history_text,
                get_cursor_position=self.get_cursor_position
            ),
            style='class:chat',
            wrap_lines=True
        )
        
        # Main split container
        main_container = HSplit([
            header_window,
            VSplit([
                sidebar_window,
                Window(width=1, char='│', style='class:sidebar.divider'),
                HSplit([
                    chat_header_window,
                    Window(height=1, char='─', style='class:sidebar.divider'),
                    chat_history_window
                ])
            ]),
            Window(height=1, char='─', style='class:sidebar.divider'),
            self.input_field
        ])

        # Key bindings
        kb = KeyBindings()

        @kb.add('c-c')
        @kb.add('c-d')
        def _exit(event):
            asyncio.create_task(self.shutdown())

        @kb.add('enter')
        def _submit(event):
            asyncio.create_task(self.handle_input())

        @kb.add('pageup')
        def _scroll_up(event):
            fragments = self.get_chat_history_text()
            line_count = sum(1 for _, text, *_ in fragments if '\n' in text)
            self.scroll_offset = min(line_count - 5, self.scroll_offset + 5)
            self.refresh()

        @kb.add('pagedown')
        def _scroll_down(event):
            self.scroll_offset = max(0, self.scroll_offset - 5)
            self.refresh()

        # Build application with mouse and complete options enabled
        self.app = Application(
            layout=Layout(main_container, focused_element=self.input_field),
            key_bindings=kb,
            style=tui_style,
            full_screen=True,
            mouse_support=True
        )
        
        # Run TUI application asynchronously
        try:
            await self.app.run_async()
        except asyncio.CancelledError:
            pass
        finally:
            await self.cleanup()

    async def shutdown(self) -> None:
        """Flags the TUI to exit."""
        if self.app:
            self.app.exit()

    async def cleanup(self) -> None:
        """Clean shutdown of networking services, db connection, and cancel background tasks."""
        # Stop background network services
        if self.discovery_service:
            try:
                await self.discovery_service.stop()
            except Exception:
                pass
        if self.tcp_service:
            try:
                await self.tcp_service.stop()
            except Exception:
                pass
            
        # Close database
        try:
            self.db_manager.close()
        except Exception:
            pass
            
        # Terminate event loop background tasks (excluding current main task)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
            
        print("\nThank you for using CliChat. Safe hacking!\n")
