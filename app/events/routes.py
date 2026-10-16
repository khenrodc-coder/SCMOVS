from app.proposals.routes import make_blueprint
from app.proposals.services import EVENT

events_bp = make_blueprint(EVENT)
