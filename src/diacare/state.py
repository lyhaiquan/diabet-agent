from dataclasses import dataclass, field


@dataclass
class State:
    question: str
    profile: dict
    history: list = field(default_factory=list)
    risk: float | None = None
    docs: list = field(default_factory=list)
    draft: str = ""
    final: str = ""
    flags: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    nutrition: dict | None = None
    patient_id: int | None = None
    memory: list = field(default_factory=list)
