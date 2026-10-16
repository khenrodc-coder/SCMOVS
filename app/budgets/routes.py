from app.finance.routes import make_blueprint
from app.finance.services import BUDGET

budgets_bp = make_blueprint(BUDGET)
