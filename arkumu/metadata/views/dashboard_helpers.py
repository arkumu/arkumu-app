"""Shared helpers for metadata and storage upload dashboards."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List

from django.utils import timezone

from arkumu.storage.models.upload_tracking import AsyncUploadFile, AsyncUploadSession


def format_size(bytes_total: int) -> str:
    """Return a human-readable string for the given byte size."""

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_total)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_file_info(files: List[AsyncUploadFile]) -> List[Dict[str, object]]:
    """Return serialisable info for files in a session."""

    info: List[Dict[str, object]] = []
    for file_obj in files:
        info.append(
            {
                "name": getattr(file_obj, "filename", ""),
                "status": file_obj.status,
                "size": getattr(file_obj, "file_size", 0) or 0,
                "content_type": getattr(file_obj, "content_type", "") or "",
                "error_message": getattr(file_obj, "error_message", "") or "",
            }
        )
    return info


@dataclass
class UploadSessionDisplay:
    """Lightweight view model mirroring legacy UploadSession fields."""

    id: str
    created_at: timezone.datetime
    completed_at: timezone.datetime | None
    status: str
    status_display: str
    user: object
    institution: str
    organization: str
    folder_name: str
    total_files: int
    completed_files: int
    failed_files: int
    uploaded_files: int
    pending_files: int
    import_stats: Dict[str, object]

    def get_status_display(self) -> str:
        return self.status_display


def _build_import_stats(session: AsyncUploadSession, files: List[AsyncUploadFile]) -> Dict[str, object]:
    total_size = sum((file.file_size or 0) for file in files)
    start_time = session.started_at or session.created_at
    end_time = session.completed_at or timezone.now()
    duration_seconds = max((end_time - start_time).total_seconds(), 0)
    error_messages = [file.error_message for file in files if file.error_message]

    return {
        "duration_seconds": duration_seconds,
        "total_size": total_size,
        "total_size_formatted": format_size(total_size),
        "summary": {
            "bucket": session.organization or "-",
            "base_path": session.base_folder or "-",
        },
        "error_count": len([file for file in files if file.status == "failed"]),
        "error": error_messages[0] if error_messages else None,
    }


def build_upload_display(
    session: AsyncUploadSession,
    files: List[AsyncUploadFile] | None = None,
) -> UploadSessionDisplay:
    if files is None:
        files = list(session.files.all())

    status_counts = Counter(file.status for file in files)
    total_files = session.total_files or len(files)

    return UploadSessionDisplay(
        id=str(session.id),
        created_at=session.created_at,
        completed_at=session.completed_at,
        status=session.status,
        status_display=session.get_status_display(),
        user=session.user,
        institution=session.organization or "Not specified",
        organization=session.organization or "",
        folder_name=session.base_folder or "",
        total_files=total_files,
        completed_files=status_counts.get("completed", 0),
        failed_files=status_counts.get("failed", 0),
        uploaded_files=status_counts.get("uploaded", 0)
        + status_counts.get("processing", 0),
        pending_files=status_counts.get("pending", 0)
        + status_counts.get("uploading", 0),
        import_stats=_build_import_stats(session, files),
    )


def build_session_entry(session: AsyncUploadSession) -> Dict[str, object]:
    files = list(session.files.all())
    display = build_upload_display(session, files)
    file_info = build_file_info(files)

    return {
        "session": display,
        "files": file_info,
        "file_count": len(file_info),
        "completed_files": display.completed_files,
        "failed_files": display.failed_files,
    }


def summarize_upload_stats(entries: List[Dict[str, object]]) -> Dict[str, object]:
    total_sessions = len(entries)
    total_files = sum(entry["file_count"] for entry in entries)
    completed_sessions = sum(1 for entry in entries if entry["session"].status == "completed")
    failed_sessions = sum(1 for entry in entries if entry["session"].status == "failed")
    in_progress_sessions = total_sessions - completed_sessions - failed_sessions

    completed_files = sum(entry["completed_files"] for entry in entries)
    failed_files = sum(entry["failed_files"] for entry in entries)
    uploaded_files = sum(entry["session"].uploaded_files for entry in entries)
    pending_files = sum(entry["session"].pending_files for entry in entries)

    return {
        "total_sessions": total_sessions,
        "total_files": total_files,
        "completed_sessions": completed_sessions,
        "failed_sessions": failed_sessions,
        "in_progress_sessions": in_progress_sessions,
        "completed_files": completed_files,
        "failed_files": failed_files,
        "uploaded_files": uploaded_files,
        "pending_files": pending_files,
    }


__all__ = [
    "build_file_info",
    "build_session_entry",
    "build_upload_display",
    "summarize_upload_stats",
    "UploadSessionDisplay",
]
