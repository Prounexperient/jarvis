"""AAA 02 — composição do plano, executor, verificador e recuperação.

Instância do núcleo é leve; sessões independentes mantêm evidências por turno.
O TaskController existente continua responsável pela autorização.
"""
from dataclasses import dataclass
from uuid import uuid4
from task_planner import TaskPlanner
from task_executor import TaskExecutor


@dataclass
class AgentSession:
    plan: object
    executor: TaskExecutor

    def summary(self):
        return self.plan.summary()


class AgentCore:
    def __init__(self, skills_manager, *, planner=None, experience_store=None):
        self.skills_manager = skills_manager
        self.planner = planner or TaskPlanner()
        self.experience_store = experience_store

    def begin(self, request):
        plan = self.planner.create(request)
        executor = TaskExecutor(self.skills_manager, plan,
                                experience_store=self.experience_store,
                                session_id=uuid4().hex)
        return AgentSession(plan, executor)
