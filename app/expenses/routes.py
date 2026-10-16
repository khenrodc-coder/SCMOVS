from app.finance.routes import make_blueprint
from app.finance.services import EXPENSE

expenses_bp = make_blueprint(EXPENSE)
