from app.proposals.routes import make_blueprint
from app.proposals.services import PROJECT

projects_bp = make_blueprint(PROJECT)
