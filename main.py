import os
import sqlite3
from typing import List, Optional, Any, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = DATABASE_URL is not None and PSYCOPG2_AVAILABLE

DB_PATH = "tickets.db"
ALLOWED_STATUSES = {"Open", "In Progress", "Closed"}
ALLOWED_PRIORITIES = {"Low", "Medium", "High", "Critical"}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
CREATE_PATH = os.path.join(BASE_DIR, "create.html")
TICKET_PATH = os.path.join(BASE_DIR, "ticket.html")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TicketCreateRequest(BaseModel):
    customer_name: str = Field(..., min_length=1)
    customer_email: EmailStr
    subject: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    priority: Optional[str] = Field("Medium", pattern="^(Low|Medium|High|Critical)$")


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    note_text: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None


class TicketCreateResponse(BaseModel):
    ticket_id: str
    created_at: str


class TicketListResponse(BaseModel):
    ticket_id: str
    customer_name: str
    customer_email: str
    subject: str
    status: str
    priority: str
    created_at: str


class NoteDetailResponse(BaseModel):
    note_text: str
    created_at: str


class TicketDetailResponse(BaseModel):
    ticket_id: str
    customer_name: str
    customer_email: str
    subject: str
    description: str
    status: str
    priority: str
    created_at: str
    updated_at: str
    notes: List[NoteDetailResponse]


# Create and return a new SQLite or PostgreSQL connection.
def get_db_connection() -> Any:
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


# Initialize the database schema if tables do not exist.
@app.on_event("startup")
def initialize_database() -> None:
    conn = get_db_connection()
    try:
        if IS_POSTGRES:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    ticket_id VARCHAR(50) UNIQUE,
                    customer_name VARCHAR(255) NOT NULL,
                    customer_email VARCHAR(255) NOT NULL,
                    subject VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'Open',
                    priority VARCHAR(50) NOT NULL DEFAULT 'Medium',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (status IN ('Open', 'In Progress', 'Closed')),
                    CHECK (priority IN ('Low', 'Medium', 'High', 'Critical'))
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id SERIAL PRIMARY KEY,
                    ticket_id VARCHAR(50) NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    note_text TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_ticket_id ON notes(ticket_id)")
            conn.commit()
            cursor.close()
        else:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT UNIQUE,
                    customer_name TEXT NOT NULL,
                    customer_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Open',
                    priority TEXT NOT NULL DEFAULT 'Medium',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (status IN ('Open', 'In Progress', 'Closed')),
                    CHECK (priority IN ('Low', 'Medium', 'High', 'Critical'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL,
                    note_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_ticket_id ON notes(ticket_id)")
            conn.commit()
    finally:
        conn.close()


# Format a numeric ticket row id into the ticket_id format.
def format_ticket_id(ticket_db_id: int) -> str:
    return f"TKT-{ticket_db_id:03d}"


# Execute queries dynamically mapping '?' placeholders to '%s' for Postgres
def db_execute(conn, query: str, params: tuple = ()) -> List[dict]:
    if not isinstance(params, (tuple, list)):
        params = (params,)
    if IS_POSTGRES:
        postgres_query = query.replace("?", "%s")
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cursor.execute(postgres_query, params)
            if cursor.description:
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            return []
        finally:
            cursor.close()
    else:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def db_execute_one(conn, query: str, params: tuple = ()) -> Optional[dict]:
    rows = db_execute(conn, query, params)
    return rows[0] if rows else None





# Create a new ticket and return it.
@app.post("/api/tickets", response_model=TicketCreateResponse, status_code=201)
def create_ticket(payload: TicketCreateRequest) -> TicketCreateResponse:
    conn = get_db_connection()
    try:
        if IS_POSTGRES:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(
                """
                INSERT INTO tickets (
                    ticket_id,
                    customer_name,
                    customer_email,
                    subject,
                    description,
                    status,
                    priority
                ) VALUES (NULL, %s, %s, %s, %s, 'Open', %s) RETURNING id
                """,
                (
                    payload.customer_name,
                    payload.customer_email,
                    payload.subject,
                    payload.description,
                    payload.priority or "Medium",
                ),
            )
            ticket_db_id = cursor.fetchone()["id"]
            cursor.close()
            
            ticket_id = format_ticket_id(ticket_db_id)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET ticket_id = %s WHERE id = %s",
                (ticket_id, ticket_db_id),
            )
            cursor.close()
        else:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    ticket_id,
                    customer_name,
                    customer_email,
                    subject,
                    description,
                    status,
                    priority,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 'Open', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    None,
                    payload.customer_name,
                    payload.customer_email,
                    payload.subject,
                    payload.description,
                    payload.priority or "Medium",
                ),
            )
            ticket_db_id = cursor.lastrowid
            ticket_id = format_ticket_id(ticket_db_id)
            conn.execute(
                "UPDATE tickets SET ticket_id = ? WHERE id = ?",
                (ticket_id, ticket_db_id),
            )
        
        conn.commit()
        row = db_execute_one(
            conn,
            "SELECT ticket_id, created_at FROM tickets WHERE id = ?",
            (ticket_db_id,),
        )
        return TicketCreateResponse(
            ticket_id=row["ticket_id"],
            created_at=str(row["created_at"])
        )
    finally:
        conn.close()


# Return all tickets, optionally filtered by status, priority, and search text.
@app.get("/api/tickets", response_model=List[TicketListResponse])
def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None
) -> List[TicketListResponse]:
    conn = get_db_connection()
    try:
        if status and status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")

        if priority and priority not in ALLOWED_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority filter")

        query = "SELECT * FROM tickets"
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if priority:
            conditions.append("priority = ?")
            params.append(priority)

        if search:
            like = f"%{search}%"
            conditions.append(
                "(customer_name LIKE ? OR customer_email LIKE ? OR subject LIKE ? OR description LIKE ? OR ticket_id LIKE ?)"
            )
            params.extend([like, like, like, like, like])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"
        rows = db_execute(conn, query, tuple(params))
        return [
            TicketListResponse(
                ticket_id=row["ticket_id"],
                customer_name=row["customer_name"],
                customer_email=row["customer_email"],
                subject=row["subject"],
                status=row["status"],
                priority=row["priority"],
                created_at=str(row["created_at"])
            )
            for row in rows
        ]
    finally:
        conn.close()


# Serve the dashboard UI.
@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(INDEX_PATH)


# Serve the create ticket page.
@app.get("/create.html")
def serve_create() -> FileResponse:
    return FileResponse(CREATE_PATH)


# Serve the ticket details page.
@app.get("/ticket.html")
def serve_ticket() -> FileResponse:
    return FileResponse(TICKET_PATH)


# Serve the dashboard UI explicitly.
@app.get("/index.html")
def serve_index_html() -> FileResponse:
    return FileResponse(INDEX_PATH)


# Provide a lightweight healthcheck for deployment monitoring.
@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


# Return a ticket and its notes by ticket_id.
@app.get("/api/tickets/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket_details(ticket_id: str) -> TicketDetailResponse:
    conn = get_db_connection()
    try:
        ticket_row = db_execute_one(
            conn,
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        )

        if not ticket_row:
            raise HTTPException(status_code=404, detail="Ticket not found")

        note_rows = db_execute(
            conn,
            "SELECT * FROM notes WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,),
        )

        notes = [
            NoteDetailResponse(
                note_text=row["note_text"],
                created_at=str(row["created_at"])
            )
            for row in note_rows
        ]
        return TicketDetailResponse(
            ticket_id=ticket_row["ticket_id"],
            customer_name=ticket_row["customer_name"],
            customer_email=ticket_row["customer_email"],
            subject=ticket_row["subject"],
            description=ticket_row["description"],
            status=ticket_row["status"],
            priority=ticket_row["priority"],
            created_at=str(ticket_row["created_at"]),
            updated_at=str(ticket_row["updated_at"]),
            notes=notes
        )
    finally:
        conn.close()


# Update a ticket status, priority, and/or add a note.
@app.put("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: str, payload: TicketUpdateRequest) -> dict:
    note_content = payload.note_text if payload.note_text is not None else payload.notes

    if payload.status is None and payload.priority is None and note_content is None:
        raise HTTPException(status_code=400, detail="At least one update field (status, priority, or notes) is required")

    if payload.status is not None and payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status value")

    if payload.priority is not None and payload.priority not in ALLOWED_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority value")

    conn = get_db_connection()
    try:
        ticket_row = db_execute_one(
            conn,
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        )

        if not ticket_row:
            raise HTTPException(status_code=404, detail="Ticket not found")

        if payload.status is not None:
            db_execute(
                conn,
                "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (payload.status, ticket_id),
            )

        if payload.priority is not None:
            db_execute(
                conn,
                "UPDATE tickets SET priority = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (payload.priority, ticket_id),
            )

        if note_content is not None:
            if IS_POSTGRES:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO notes (ticket_id, note_text, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP)",
                    (ticket_id, note_content),
                )
                cursor.execute(
                    "UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE ticket_id = %s",
                    (ticket_id,),
                )
                cursor.close()
            else:
                conn.execute(
                    "INSERT INTO notes (ticket_id, note_text, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (ticket_id, note_content),
                )
                conn.execute(
                    "UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                    (ticket_id,),
                )

        conn.commit()
        updated_row = db_execute_one(
            conn,
            "SELECT updated_at FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        )
        return {"success": True, "updated_at": str(updated_row["updated_at"])}
    finally:
        conn.close()


# Terminal commands to install dependencies and run the server:
# pip install fastapi uvicorn pydantic
# uvicorn main:app --reload
