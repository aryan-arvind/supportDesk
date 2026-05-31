# SupportDesk

SupportDesk is a simple customer support ticket system with a FastAPI backend and a lightweight HTML dashboard.

## Features

- Create tickets with customer details and descriptions
- List, search, and filter tickets by status
- View ticket details and add notes
- Update ticket status

## API overview

- `POST /api/tickets`
- `GET /api/tickets`
- `GET /api/tickets/{ticket_id}`
- `PUT /api/tickets/{ticket_id}`
- `GET /health`

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `index.html` in your browser to use the UI.

## Deploy on Railway

1. Connect this GitHub repo in Railway.
2. Railway uses `railway.json` and starts the app automatically.
3. Verify the service is live at `/health`.
