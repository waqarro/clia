import socket
import asyncio
import logging
from typing import Callable, List, Optional
from protocol.packets import (
    create_discovery_packet,
    create_discovery_response_packet,
    create_status_update_packet,
    parse_packet,
    serialize_packet
)
from storage.db import DatabaseManager

class DiscoveryProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol handler for receiving and replying to discovery packets."""
    
    def __init__(self, service: 'DiscoveryService'):
        super().__init__()
        self.service = service

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport
        self.service.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            raw_str = data.decode('utf-8').strip()
            # Split lines in case multiple packets were concatenated in buffer
            for line in raw_str.split('\n'):
                if not line:
                    continue
                packet = parse_packet(line)
                if not packet:
                    continue
                
                sender = packet.get("sender")
                # Ignore discovery broadcast from ourselves
                if sender == self.service.username:
                    continue
                
                packet_type = packet.get("type")
                ip = packet.get("ip", addr[0])
                port = packet.get("port")
                groups = packet.get("groups", [])
                
                if packet_type in ("discovery", "discovery_response", "status_update"):
                    status = "online"
                    if packet_type == "status_update":
                        status = packet.get("status", "online")
                    
                    # Store or update the peer's record
                    self.service.db_manager.save_peer(sender, ip, port, status)
                    
                    # Store group membership local cache for peer if present
                    # (For group chats: we track which peers are joined to which groups)
                    self.service.update_peer_groups(sender, groups)
                    
                    # Notify UI that peers have updated
                    if self.service.ui_callback:
                        self.service.ui_callback()
                    
                    # If they broadcasted discovery, reply with a direct discovery response
                    if packet_type == "discovery" and status == "online":
                        response = create_discovery_response_packet(
                            self.service.username,
                            self.service.local_ip,
                            self.service.tcp_port,
                            self.service.db_manager.get_joined_groups()
                        )
                        # Send back directly to the address of the broadcast sender
                        self.transport.sendto(serialize_packet(response).encode('utf-8'), addr)
                        
                elif packet_type == "join_group":
                    group = packet.get("group")
                    self.service.add_peer_to_group(sender, group)
                    if self.service.ui_callback:
                        self.service.ui_callback()
                        
                elif packet_type == "leave_group":
                    group = packet.get("group")
                    self.service.remove_peer_from_group(sender, group)
                    if self.service.ui_callback:
                        self.service.ui_callback()
                        
        except Exception as e:
            # Silently catch packet decoding errors in local network environment
            pass

class DiscoveryService:
    """Manages UDP broadcast discovery loop and maps online peers' active groups."""
    
    def __init__(
        self,
        username: str,
        local_ip: str,
        tcp_port: int,
        discovery_port: int,
        db_manager: DatabaseManager,
        ui_callback: Optional[Callable[[], None]] = None
    ):
        self.username = username
        self.local_ip = local_ip
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.db_manager = db_manager
        self.ui_callback = ui_callback
        
        self.transport = None
        self.running = False
        self.broadcast_task = None
        
        # In-memory mapping: group_name -> Set[peer_username]
        # Tracks which discovered peers are currently joined to which group
        self.peer_groups = {}

    def update_peer_groups(self, peer: str, groups: List[str]) -> None:
        """Updates the local cache of what groups a peer belongs to."""
        # Remove peer from all groups first
        for g_members in self.peer_groups.values():
            g_members.discard(peer)
        
        # Add to current groups
        for g in groups:
            if g not in self.peer_groups:
                self.peer_groups[g] = set()
            self.peer_groups[g].add(peer)

    def add_peer_to_group(self, peer: str, group: str) -> None:
        if group not in self.peer_groups:
            self.peer_groups[group] = set()
        self.peer_groups[group].add(peer)

    def remove_peer_from_group(self, peer: str, group: str) -> None:
        if group in self.peer_groups:
            self.peer_groups[group].discard(peer)

    def get_group_members(self, group: str) -> List[str]:
        """Returns online peers who are in the specified group."""
        return list(self.peer_groups.get(group, set()))

    async def start(self) -> None:
        """Binds socket and starts discovery broad-listen operations."""
        self.running = True
        
        # Create standard reusable socket for UDP binding
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', self.discovery_port))
        
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(self),
            sock=sock
        )
        
        # Send initial broadcast immediately, then launch periodic loop
        self.broadcast_task = asyncio.create_task(self.broadcast_loop())

    async def broadcast_loop(self) -> None:
        """Periodically sends discovery broadcasts to notify the network."""
        while self.running:
            try:
                packet = create_discovery_packet(
                    self.username,
                    self.local_ip,
                    self.tcp_port,
                    self.db_manager.get_joined_groups()
                )
                data = serialize_packet(packet).encode('utf-8')
                if self.transport:
                    self.transport.sendto(data, ('255.255.255.255', self.discovery_port))
            except Exception:
                pass
            await asyncio.sleep(5)

    async def notify_status_change(self, status: str) -> None:
        """Broadcasts a status update (like 'offline' on shutdown) to all peers."""
        try:
            packet = create_status_update_packet(
                self.username,
                status,
                self.local_ip,
                self.tcp_port,
                self.db_manager.get_joined_groups()
            )
            data = serialize_packet(packet).encode('utf-8')
            if self.transport:
                self.transport.sendto(data, ('255.255.255.255', self.discovery_port))
        except Exception:
            pass

    async def notify_group_action(self, action: str, group_name: str) -> None:
        """Broadcasts group membership events to all peers."""
        try:
            if action == "join":
                packet = create_join_group_packet(self.username, group_name)
            else:
                packet = create_leave_group_packet(self.username, group_name)
            data = serialize_packet(packet).encode('utf-8')
            if self.transport:
                self.transport.sendto(data, ('255.255.255.255', self.discovery_port))
        except Exception:
            pass

    async def stop(self) -> None:
        """Stops discovery, announces offline status, and closes socket."""
        self.running = False
        if self.broadcast_task:
            self.broadcast_task.cancel()
        await self.notify_status_change("offline")
        if self.transport:
            self.transport.close()
