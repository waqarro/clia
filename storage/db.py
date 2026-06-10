import sqlite3
import os
from typing import List, Dict, Any, Tuple
from datetime import datetime

class DatabaseManager:
    """Manages local SQLite database for peer info, message history, and group memberships."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.connect()
        self.init_db()

    def connect(self) -> None:
        """Establishes connection to the SQLite database."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        except Exception as e:
            print(f"Database connection error: {e}")

    def close(self) -> None:
        """Closes the database connection."""
        if self.conn:
            self.conn.close()

    def init_db(self) -> None:
        """Initializes database tables if they do not exist."""
        cursor = self.conn.cursor()
        
        # Table to store known peers
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS peers (
                username TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'offline'
            )
        """)
        
        # Table to store message history (private and group messages)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                target TEXT NOT NULL,
                type TEXT NOT NULL, -- 'private' or 'group'
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        
        # Table to store groups we have joined/known
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                name TEXT PRIMARY KEY,
                joined INTEGER DEFAULT 0 -- 1 if we are a member, 0 otherwise
            )
        """)
        
        self.conn.commit()

    # --- PEER OPERATIONS ---
    
    def save_peer(self, username: str, ip: str, port: int, status: str = 'online') -> None:
        """Saves or updates a peer's network and status details."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO peers (username, ip, port, last_seen, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                ip = excluded.ip,
                port = excluded.port,
                last_seen = excluded.last_seen,
                status = excluded.status
        """, (username, ip, port, now, status))
        self.conn.commit()

    def update_peer_status(self, username: str, status: str) -> None:
        """Updates a peer's online/offline status."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE peers 
            SET status = ?, last_seen = ? 
            WHERE username = ?
        """, (status, datetime.now().isoformat(), username))
        self.conn.commit()

    def get_peer(self, username: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a single peer by username."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM peers WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def get_all_peers(self) -> List[Dict[str, Any]]:
        """Retrieves all stored peers."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM peers ORDER BY status DESC, username ASC")
        return [dict(row) for row in cursor.fetchall()]

    # --- MESSAGE OPERATIONS ---
    
    def save_message(self, sender: str, target: str, msg_type: str, content: str, timestamp: str = None) -> None:
        """Saves a message in the chat database."""
        if not timestamp:
            timestamp = datetime.now().isoformat()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO messages (sender, target, type, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (sender, target, msg_type, content, timestamp))
        self.conn.commit()

    def get_chat_history(self, current_user: str, chat_target: str, msg_type: str) -> List[Dict[str, Any]]:
        """
        Retrieves message history for private or group chat.
        If msg_type is 'private', it gets messages between current_user and chat_target.
        If msg_type is 'group', it gets all messages sent to that group.
        """
        cursor = self.conn.cursor()
        if msg_type == 'private':
            cursor.execute("""
                SELECT * FROM messages 
                WHERE (type = 'private') AND (
                    (sender = ? AND target = ?) OR 
                    (sender = ? AND target = ?)
                )
                ORDER BY timestamp ASC
            """, (current_user, chat_target, chat_target, current_user))
        else:  # group message
            cursor.execute("""
                SELECT * FROM messages 
                WHERE type = 'group' AND target = ?
                ORDER BY timestamp ASC
            """, (chat_target,))
        
        return [dict(row) for row in cursor.fetchall()]

    def clear_chat_history(self, current_user: str, chat_target: str, msg_type: str) -> None:
        """Clears message history for a specific conversation."""
        cursor = self.conn.cursor()
        if msg_type == 'private':
            cursor.execute("""
                DELETE FROM messages 
                WHERE (type = 'private') AND (
                    (sender = ? AND target = ?) OR 
                    (sender = ? AND target = ?)
                )
            """, (current_user, chat_target, chat_target, current_user))
        else:
            cursor.execute("""
                DELETE FROM messages 
                WHERE type = 'group' AND target = ?
            """, (chat_target,))
        self.conn.commit()

    # --- GROUP OPERATIONS ---
    
    def create_or_join_group(self, group_name: str) -> None:
        """Creates a group entry and marks it as joined."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO groups (name, joined)
            VALUES (?, 1)
            ON CONFLICT(name) DO UPDATE SET joined = 1
        """, (group_name,))
        self.conn.commit()

    def leave_group(self, group_name: str) -> None:
        """Marks a group as left."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE groups SET joined = 0 WHERE name = ?
        """, (group_name,))
        self.conn.commit()

    def get_joined_groups(self) -> List[str]:
        """Retrieves names of all groups the user has joined."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM groups WHERE joined = 1 ORDER BY name ASC")
        return [row['name'] for row in cursor.fetchall()]

    def is_group_joined(self, group_name: str) -> bool:
        """Checks if a group is currently joined by the user."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT joined FROM groups WHERE name = ?", (group_name,))
        row = cursor.fetchone()
        if row and row['joined'] == 1:
            return True
        return False
