from flask import Blueprint, render_template, request

from app.audit import services
from app.auth.decorators import access_required

audit_bp = Blueprint("audit", __name__, url_prefix="/audit-logs")

# Super Admin only (audit.view). The page is read-only: there is no way to edit or delete a log.
view_access = access_required(("super_admin",), "audit.view")


@audit_bp.route("")
@view_access
def list_page():
    data = services.list_logs(request.args)
    return render_template("audit/list.html", filters=data["base_filters"],
                           options=services.get_filter_options(), **data)
