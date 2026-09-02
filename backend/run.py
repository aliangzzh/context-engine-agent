"""Backend entrypoint: `python run.py`.

Serves the zero-dependency stdlib HTTP server (no pip install needed).
To use FastAPI instead: `pip install fastapi uvicorn` then `uvicorn app.main:app`.
"""
import server

if __name__ == "__main__":
    server.main()
