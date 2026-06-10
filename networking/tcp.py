import asyncio
import logging
from typing import Callable, Optional, List, Any
from protocol.packets import (
    create_private_message_packet,
    create_group_message_packet,
    create_discovery_response_packet,
    parse_packet,
    serialize_packet
)
from storage.db import DatabaseManager

class TcpService:
    """Manages the TCP server for receiving messages and handles outgoing client TCP messages."""

    def __init__(
        self,
        username: str,
        db_manager: DatabaseManager,
        discovery_service: Any = None,
        ui_msg_callback: Optional[Callable[[dict], None]] = None,
        ui_status_callback: Optional[Callable[[], None]] = None
    ):
        self.username = username
        self.db_manager = db_manager
        self.discovery_service = discovery_service
        self.ui_msg_callback = ui_msg_callback
        self.ui_status_callback = ui_status_callback
        
        self.server = None
        self.port = None
        self.running = False

    def set_discovery_service(self, discovery_service) -> None:
        self.discovery_service = discovery_service

    async def start(self, start_port: int = 50002) -> int:
        """
        Starts the TCP server. If the preferred port is taken,
        it increments sequentially until it finds a free one.
        Returns the port it successfully bound to.
        """
        self.running = True
        self.port = start_port
        
        while self.running:
            try:
                self.server = await asyncio.start_server(
                    self.handle_incoming_connection,
                    '0.0.0.0',
                    self.port
                )
                break
            except OSError:
                # Port is already in use, try next one
                self.port += 1
                if self.port > 65535:
                    raise RuntimeError("No free TCP ports available.")
        
        # Run server in the background
        asyncio.create_task(self.server.serve_forever())
        return self.port

    async def handle_incoming_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """Handles a single incoming peer connection and reads its JSON packet stream."""
        try:
            while self.running:
                data = await reader.readline()
                if not data:
                    break
                
                raw_str = data.decode('utf-8').strip()
                packet = parse_packet(raw_str)
                if not packet:
                    continue
                
                packet_type = packet.get("type")
                sender = packet.get("sender")
                
                if packet_type == "private_message":
                    content = packet.get("message")
                    ts = packet.get("timestamp")
                    # Save to db
                    self.db_manager.save_message(sender, self.username, "private", content, ts)
                    # Trigger UI
                    if self.ui_msg_callback:
                        self.ui_msg_callback(packet)
                        
                elif packet_type == "group_message":
                    group_name = packet.get("target")
                    content = packet.get("message")
                    ts = packet.get("timestamp")
                    # Check if we are actually in this group
                    if self.db_manager.is_group_joined(group_name):
                        # Save to db
                        self.db_manager.save_message(sender, group_name, "group", content, ts)
                        # Trigger UI
                        if self.ui_msg_callback:
                            self.ui_msg_callback(packet)
                            
                elif packet_type == "discovery":
                    ip = packet.get("ip")
                    if not ip or ip == "127.0.0.1":
                        ip = writer.get_extra_info('peername')[0]
                    port = packet.get("port")
                    groups = packet.get("groups", [])
                    
                    # Save peer to DB
                    self.db_manager.save_peer(sender, ip, port, "online")
                    if self.discovery_service:
                        self.discovery_service.update_peer_groups(sender, groups)
                        
                    # Trigger UI status update
                    if self.ui_status_callback:
                        self.ui_status_callback()
                        
                    # Reply immediately with TCP discovery response
                    response = create_discovery_response_packet(
                        self.username,
                        self.discovery_service.local_ip if self.discovery_service else "127.0.0.1",
                        self.port,
                        self.db_manager.get_joined_groups()
                    )
                    writer.write(serialize_packet(response).encode('utf-8'))
                    await writer.drain()

                elif packet_type == "ping":
                    # Peer is keeping connection/liveness, last_seen is updated via discovery usually
                    pass
        except (asyncio.CancelledError, ConnectionResetError, OSError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def send_private_message(self, target_username: str, message: str) -> bool:
        """
        Sends a private message to a specific peer over TCP.
        Looks up their IP and port from the local DB.
        """
        peer = self.db_manager.get_peer(target_username)
        if not peer or peer.get("status") != "online":
            return False
            
        ip = peer.get("ip")
        port = peer.get("port")
        
        packet = create_private_message_packet(self.username, target_username, message)
        data = serialize_packet(packet).encode('utf-8')
        
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=3.0
            )
            writer.write(data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            
            # Save the message in our own DB as sent
            self.db_manager.save_message(self.username, target_username, "private", message)
            return True
        except Exception:
            # If connection failed, mark peer as offline (self-healing)
            self.db_manager.update_peer_status(target_username, "offline")
            if self.ui_status_callback:
                self.ui_status_callback()
            return False

    async def send_group_message(self, group_name: str, message: str) -> int:
        """
        Sends a group message to all online peers joined in the group.
        Returns the number of peers the message was successfully delivered to.
        """
        if not self.db_manager.is_group_joined(group_name):
            return 0
            
        # Get list of online peers who are also in this group
        online_members = []
        if self.discovery_service:
            online_members = self.discovery_service.get_group_members(group_name)
            
        packet = create_group_message_packet(self.username, group_name, message)
        data = serialize_packet(packet).encode('utf-8')
        
        success_count = 0
        tasks = []
        
        async def send_to_peer(peer_username: str):
            nonlocal success_count
            peer = self.db_manager.get_peer(peer_username)
            if not peer or peer.get("status") != "online":
                return
            ip = peer.get("ip")
            port = peer.get("port")
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=2.0
                )
                writer.write(data)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                success_count += 1
            except Exception:
                # Mark as offline if unreachable
                self.db_manager.update_peer_status(peer_username, "offline")
                if self.ui_status_callback:
                    self.ui_status_callback()

        # Send to all peers concurrently
        if online_members:
            await asyncio.gather(*(send_to_peer(m) for m in online_members), return_exceptions=True)
            
        # Save group message to our database
        self.db_manager.save_message(self.username, group_name, "group", message)
        return success_count

    async def stop(self) -> None:
        """Closes the TCP server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
