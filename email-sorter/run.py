from app.config import settings
from app.server import create_app

app = create_app()

if __name__ == "__main__":
    # Bound to localhost only: your emails never leave this machine.
    app.run(host="127.0.0.1", port=settings.port, debug=False)
