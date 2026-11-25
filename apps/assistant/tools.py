"""The assistant's tools: read-only questions the model may ask about the school.

Each tool is bound to the signed-in user and reads only through that user's own selectors, so
the model sees exactly what the user could open in EduNexa, never more. The model can't name
another user, and a record outside the user's scope looks the same as one that doesn't exist.
No tool writes anything.
"""

import json
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from langchain_core.tools import tool

from apps.academics.models import TimetableSlot
from apps.academics.selectors import classrooms, teacher_lessons
from apps.accounts.models import User
from apps.attendance.models import Attendance, LeaveRequest
from apps.attendance.selectors import leave_requests
from apps.communication.selectors import announcements
from apps.exams.models import Exam
from apps.exams.selectors import exams
from apps.fees.models import rupees
from apps.fees.selectors import OPEN, fee_summary, invoices, overdue, totals
from apps.reports.selectors import low_attendance, overview, student_report, to_do
from apps.students.selectors import enrollments, students

LIST_LIMIT = 15
DAYS = {label.lower(): value for value, label in TimetableSlot.Day.choices}


def as_json(data):
    return json.dumps(data, default=str, ensure_ascii=False)


def classroom_name(classroom):
    return f"{classroom.grade}-{classroom.section}"


def current_classes(user, pupils):
    """{student id: class name} for each student's latest class the user may see."""
    found = {}
    for enrollment in (
        enrollments(user)
        .filter(student__in=pupils, left_on__isnull=True)
        .order_by("year__starts_on", "pk")
    ):
        found[enrollment.student_id] = classroom_name(enrollment.classroom)
    return found


def tools_for(user):
    """The tools this user's assistant may call. A tool the role has no use for (fees for a
    teacher, the school overview for a parent) isn't offered at all."""
    offered = []

    def offer(function):
        offered.append(tool(function))
        return function

    if user.role in User.ACADEMIC:

        @offer
        def find_students(name: str = "") -> str:
            """Find students by name or admission number. Students and parents get their own
            records (the name can be left empty). Returns each student's id for student_record."""
            pupils = students(user)
            if user.role in User.STAFF:
                if len(name.strip()) < 2:
                    return "Give at least two letters of a name or an admission number."
                for word in name.split():
                    pupils = pupils.filter(
                        Q(user__first_name__icontains=word)
                        | Q(user__last_name__icontains=word)
                        | Q(admission_number__icontains=word)
                    )
            pupils = list(pupils.order_by("user__first_name", "pk")[:LIST_LIMIT])
            classes = current_classes(user, pupils)
            return as_json(
                [
                    {
                        "student_id": pupil.pk,
                        "name": pupil.user.display_name,
                        "admission_number": pupil.admission_number,
                        "class": classes.get(pupil.pk),
                        "branch": pupil.user.branch.name,
                        "active": pupil.user.is_active,
                    }
                    for pupil in pupils
                ]
            )

        @offer
        def student_record(student_id: int) -> str:
            """One student's record for their latest academic year: attendance totals and rate,
            recent absences, and published exam results with grades. Get the id from
            find_students."""
            student = students(user).filter(pk=student_id).first()
            if student is None:
                return "No student with that id is in your records."
            report = student_report(user, student)
            summary = report["attendance_summary"]
            absences = report["attendance_rows"].filter(status=Attendance.Status.ABSENT)
            marks = sorted(report["marks"], key=lambda m: (m.exam.date, m.pk), reverse=True)
            return as_json(
                {
                    "name": student.user.display_name,
                    "admission_number": student.admission_number,
                    "year": str(report["selected_year"] or ""),
                    "classes": [classroom_name(e.classroom) for e in report["enrollments"]],
                    "attendance": {
                        **{label: summary[value] for value, label in Attendance.Status.choices},
                        "days_recorded": summary["total"],
                        "rate_percent": summary["rate"],
                        "below_75_percent": summary["below_minimum"],
                        "recent_absences": [row.session.date for row in absences[:10]],
                    },
                    "results": {
                        "published_exams": report["summary"]["count"],
                        "passed": report["summary"]["passed"],
                        "overall_percent": report["summary"]["percentage"],
                        "overall_grade": str(report["summary"]["grade"] or "") or None,
                        "latest": [
                            {
                                "exam": mark.exam.title,
                                "subject": mark.exam.subject.name,
                                "date": mark.exam.date,
                                "term": mark.exam.term.name,
                                "score": "absent" if mark.absent else mark.score,
                                "out_of": mark.exam.max_marks,
                                "grade": mark.grade_label,
                                "passed": mark.passed,
                            }
                            for mark in marks[:LIST_LIMIT]
                        ],
                    },
                }
            )

        @offer
        def list_exams(status: str = "") -> str:
            """Recent exams, newest first, with their class, subject, date and status (draft,
            submitted or published). Optionally only one status. Families see published exams
            only."""
            found = exams(user)
            if status.lower() in Exam.Status.values:
                found = found.filter(status=status.lower())
            return as_json(
                [
                    {
                        "exam": exam.title,
                        "subject": exam.subject.name,
                        "class": classroom_name(exam.classroom),
                        "date": exam.date,
                        "term": exam.term.name,
                        "status": exam.get_status_display(),
                        "max_marks": exam.max_marks,
                    }
                    for exam in found.order_by("-date", "-pk")[:LIST_LIMIT]
                ]
            )

        @offer
        def list_leave_requests(status: str = "") -> str:
            """Leave requests for the students in your records, newest first, with dates,
            reason and decision. Optionally only one status: pending, approved or rejected."""
            found = leave_requests(user)
            if status.lower() in LeaveRequest.Status.values:
                found = found.filter(status=status.lower())
            return as_json(
                [
                    {
                        "student": leave.student.user.display_name,
                        "from": leave.starts_on,
                        "to": leave.ends_on,
                        "reason": leave.reason,
                        "status": leave.get_status_display(),
                        "decided_by": leave.decided_by.display_name if leave.decided_by else None,
                    }
                    for leave in found.order_by("-starts_on", "-pk")[:LIST_LIMIT]
                ]
            )

    if user.role in User.STAFF:

        @offer
        def school_overview() -> str:
            """Headline numbers for your classes: active students, classes, exams waiting for a
            principal, today's attendance rate, your to-do list, and students below 75%
            attendance."""
            numbers = overview(user)
            waiting = to_do(user)
            return as_json(
                {
                    "today": numbers["today"],
                    "active_students": numbers["stats"]["students"],
                    "classes": numbers["stats"]["classes"],
                    "exams_awaiting_approval": numbers["stats"]["pending"],
                    "attendance_today_percent": numbers["stats"]["attendance"],
                    "to_do": {
                        "mark_sheets_to_complete": waiting["drafts_count"],
                        "exams_to_publish": waiting["awaiting_count"],
                        "leave_requests_to_decide": waiting["leave_count"],
                    },
                    "below_75_percent_attendance": low_attendance(user),
                }
            )

    if user.is_finance or user.is_parent:

        @offer
        def fees_overview() -> str:
            """Fees. Finance staff: amounts billed, collected and outstanding, today's
            collections and the most overdue invoices. Parents: their children's unpaid
            invoices and what is owed."""
            today = timezone.localdate()
            scope = invoices(user)
            if user.is_parent:
                unpaid = scope.filter(status__in=OPEN).order_by("due_on", "pk")
                return as_json(
                    {
                        "outstanding": rupees(totals(unpaid)["outstanding"]),
                        "unpaid_invoices": [invoice_row(i, today) for i in unpaid[:LIST_LIMIT]],
                    }
                )
            summary = fee_summary(user, today=today)
            late = overdue(scope, today).order_by("due_on", "pk")
            return as_json(
                {
                    "billed": rupees(summary["billed"]),
                    "collected": rupees(summary["collected"]),
                    "outstanding": rupees(summary["outstanding"]),
                    "collected_today": rupees(summary["collected_today"]),
                    "overdue_invoices": summary["overdue"],
                    "payments_to_check": summary["to_check"],
                    "most_overdue": [invoice_row(i, today) for i in late[:LIST_LIMIT]],
                }
            )

    if user.role == User.Role.TEACHER or user.is_family:

        @offer
        def timetable(day: str = "today") -> str:
            """Lessons on one day, in period order: today, tomorrow or a weekday name such as
            Monday. A teacher gets their own lessons; a student or parent gets the class
            timetable."""
            day = day.strip().lower()
            date = timezone.localdate()
            if day == "tomorrow":
                date += timedelta(days=1)
            weekday = DAYS.get(day, date.isoweekday())
            if user.role == User.Role.TEACHER:
                lessons = teacher_lessons(user)
            else:
                lessons = TimetableSlot.objects.filter(
                    classroom__in=classrooms(user)
                ).select_related("classroom__grade", "period", "subject", "teacher")
            lessons = lessons.filter(
                weekday=weekday, year__starts_on__lte=date, year__ends_on__gte=date
            ).order_by("period__number", "classroom__grade", "classroom__section")
            return as_json(
                {
                    "day": TimetableSlot.Day(weekday).label,
                    "lessons": [
                        {
                            "period": lesson.period.number,
                            "time": f"{lesson.period.starts_at:%H:%M}-{lesson.period.ends_at:%H:%M}",
                            "class": classroom_name(lesson.classroom),
                            "subject": lesson.subject.name,
                            "teacher": lesson.teacher.display_name,
                        }
                        for lesson in lessons
                    ],
                }
            )

    @offer
    def latest_announcements() -> str:
        """The five newest announcements meant for you, with their text."""
        return as_json(
            [
                {
                    "title": item.title,
                    "date": item.created_at.date(),
                    "from": item.author.display_name,
                    "text": item.body[:800],
                }
                for item in announcements(user).order_by("-created_at", "-pk")[:5]
            ]
        )

    return offered


def invoice_row(invoice, today):
    return {
        "invoice": f"#{invoice.pk}",
        "student": invoice.student.user.display_name,
        "title": invoice.title,
        "due_on": invoice.due_on,
        "overdue": invoice.due_on < today,
        "total": rupees(invoice.total_paise),
        "balance": rupees(invoice.balance_paise),
    }
