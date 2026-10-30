import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, render_template, request

import routes.complaint_routes as cr
from services import analytics
from services.auth import roles_required

bp = Blueprint("dashboard", __name__)


def _filtered():
    a = request.args
    return analytics.apply_filters(cr._load(), a.get("from"), a.get("to"), a.get("department"), a.get("agent"))


@bp.get("/dashboard")
def page():
    return render_template("dashboard.html")


@bp.get("/dashboard/data")
@roles_required("supervisor", "admin")
def data():
    result = analytics.kpis(_filtered())
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(result)


@bp.get("/dashboard/report.csv")
@roles_required("supervisor", "admin")
def report():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(analytics.REPORT_COLUMNS)
    w.writerows(analytics.report_rows(_filtered()))
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=complaints_report.csv"})
