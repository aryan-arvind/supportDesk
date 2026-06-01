import os
import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

DB_PATH = "tickets.db"
ALLOWED_STATUSES = {"Open", "In Progress", "Closed"}
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


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    note_text: Optional[str] = None


class TicketResponse(BaseModel):
    id: int
    ticket_id: str
    customer_name: str
    customer_email: str
    subject: str
    description: str
    status: str
    priority: str
    created_at: str
    updated_at: str


class NoteResponse(BaseModel):
    id: int
    ticket_id: str
    note_text: str
    created_at: str


class TicketWithNotesResponse(TicketResponse):
    notes: List[NoteResponse]


# Create and return a new SQLite connection.
def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Initialize the database schema if tables do not exist.
@app.on_event("startup")
def initialize_database() -> None:
    conn = get_db_connection()
    try:
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


# Convert a ticket row into a response model.
def map_ticket_row(row: sqlite3.Row) -> TicketResponse:
    return TicketResponse(
        id=row["id"],
        ticket_id=row["ticket_id"],
        customer_name=row["customer_name"],
        customer_email=row["customer_email"],
        subject=row["subject"],
        description=row["description"],
        status=row["status"],
        priority=row["priority"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# Convert a note row into a response model.
def map_note_row(row: sqlite3.Row) -> NoteResponse:
    return NoteResponse(
        id=row["id"],
        ticket_id=row["ticket_id"],
        note_text=row["note_text"],
        created_at=row["created_at"],
    )


# Create a new ticket and return it.
@app.post("/api/tickets", response_model=TicketResponse, status_code=201)
def create_ticket(payload: TicketCreateRequest) -> TicketResponse:
    conn = get_db_connection()
    try:
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
            ) VALUES (?, ?, ?, ?, ?, 'Open', 'Medium', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                None,
                payload.customer_name,
                payload.customer_email,
                payload.subject,
                payload.description,
            ),
        )
        ticket_db_id = cursor.lastrowid
        ticket_id = format_ticket_id(ticket_db_id)
        conn.execute(
            "UPDATE tickets SET ticket_id = ? WHERE id = ?",
            (ticket_id, ticket_db_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tickets WHERE id = ?",
            (ticket_db_id,),
        ).fetchone()
        return map_ticket_row(row)
    finally:
        conn.close()


# Return all tickets, optionally filtered by status and search text.
@app.get("/api/tickets", response_model=List[TicketResponse])
def list_tickets(status: Optional[str] = None, search: Optional[str] = None) -> List[TicketResponse]:
    conn = get_db_connection()
    try:
        if status and status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")

        query = "SELECT * FROM tickets"
        conditions = []
        params: List[str] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if search:
            like = f"%{search}%"
            conditions.append(
                "(customer_name LIKE ? OR customer_email LIKE ? OR subject LIKE ? OR description LIKE ? OR ticket_id LIKE ?)"
            )
            params.extend([like, like, like, like, like])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [map_ticket_row(row) for row in rows]
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
@app.get("/api/tickets/{ticket_id}", response_model=TicketWithNotesResponse)
def get_ticket_details(ticket_id: str) -> TicketWithNotesResponse:
    conn = get_db_connection()
    try:
        ticket_row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()

        if not ticket_row:
            raise HTTPException(status_code=404, detail="Ticket not found")

        note_rows = conn.execute(
            "SELECT * FROM notes WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,),
        ).fetchall()

        ticket = map_ticket_row(ticket_row)
        notes = [map_note_row(row) for row in note_rows]
        return TicketWithNotesResponse(**ticket.model_dump(), notes=notes)
    finally:
        conn.close()


# Update a ticket status and/or add a note.
@app.put("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: str, payload: TicketUpdateRequest) -> dict:
    if payload.status is None and payload.note_text is None:
        raise HTTPException(status_code=400, detail="status or note_text is required")

    if payload.status is not None and payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status value")

    conn = get_db_connection()
    try:
        ticket_row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()

        if not ticket_row:
            raise HTTPException(status_code=404, detail="Ticket not found")

        if payload.status is not None:
            conn.execute(
                "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (payload.status, ticket_id),
            )

        if payload.note_text is not None:
            conn.execute(
                "INSERT INTO notes (ticket_id, note_text, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (ticket_id, payload.note_text),
            )
            conn.execute(
                "UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (ticket_id,),
            )

        conn.commit()
        updated_row = conn.execute(
            "SELECT updated_at FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        return {"success": True, "updated_at": updated_row["updated_at"]}
    finally:
        conn.close()


# Terminal commands to install dependencies and run the server:
# pip install fastapi uvicorn pydantic
# uvicorn main:app --reload
