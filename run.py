
import os
import shutil
from dotenv import load_dotenv
from app import create_app

load_dotenv()

app = create_app()

# TEMPORARY: Diagnose MySQL backup tools on Railway
for name in ("mysqldump", "mysql"):
    env_name = "MYSQLDUMP_PATH" if name == "mysqldump" else "MYSQL_PATH"
    configured = os.environ.get(env_name, name)

    print(
        f"[BACKUP CHECK] {name}: "
        f"configured={configured}, "
        f"exists={os.path.isfile(configured)}, "
        f"found={shutil.which(name)}"
    )

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug)
