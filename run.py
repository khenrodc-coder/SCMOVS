import os
from app import create_app
from dotenv import load_dotenv
load_dotenv()
app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug)
