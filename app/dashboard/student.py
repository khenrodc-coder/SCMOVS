"""Data for the Student dashboard (Phase 7A). Everything comes from the database."""
from app.dashboard.officer import recent_notifications
from app.voting import services as voting
from app.announcements.services import visible_for


def student_announcements(student, limit=4):
    """Published announcements for all students, or for this student's department."""
    return fetch_all(
        "SELECT a.id, a.title, a.content, a.publish_at, a.created_at, u.full_name AS author "
        "FROM announcements a JOIN users u ON u.id = a.author_id "
        "WHERE a.status = 'published' AND (a.publish_at IS NULL OR a.publish_at <= NOW()) "
        "AND (a.target_audience = 'all_students' "
        "     OR (a.target_audience = 'department' AND a.department_id = %s)) "
        "ORDER BY COALESCE(a.publish_at, a.created_at) DESC, a.id DESC LIMIT " + str(limit), (student["department_id"],))


def overview(user):
    student = voting.get_student(user["id"])
    data = {"student": student, "elections": [], "open_count": 0, "voted_count": 0,
            "notifications": [], "unread": 0, "announcements": []}
    data["notifications"], data["unread"] = recent_notifications(user["id"])
    if student is None:
        return data
    elections = voting.list_elections(student)
    data["elections"] = elections
    data["open_count"] = sum(1 for e in elections if e["can_vote"])
    data["voted_count"] = sum(1 for e in elections if e["state"] == "voted")
    data["announcements"] = visible_for(user)
    return data
