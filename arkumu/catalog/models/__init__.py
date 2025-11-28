from .preview_imgs import *
from .project_index import ProjectDetailIndex, ProjectIndex, ProjectRecordIndex

__all__ = [
    "PreviewImages",
    "ProjectIndex",
    # Backwards compatibility aliases (both point to ProjectIndex)
    "ProjectDetailIndex",
    "ProjectRecordIndex",
]
