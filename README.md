# SupportDesk

## Deploy (Railway)

1. Push this repo to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Railway will detect `railway.json` and use the start command automatically.
4. Confirm the service is up by visiting `/health` on your Railway URL.

### Local run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
