from enum import Enum


class SessionStatus(str, Enum):
    INIT = "init"
    PERCEIVED = "perceived"
    DIAGNOSED = "diagnosed"
    DIAGNOSIS_VALIDATED = "diagnosis_validated"
    PLANNED = "planned"
    SOLUTION_VALIDATED = "solution_validated"
    HUMAN_REVIEWED = "human_reviewed"
    CLOSED = "closed"
    ERROR = "error"
