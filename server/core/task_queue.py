import asyncio
import uuid
import time
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    def __init__(self, service: str, action: str, params: dict, count: int = 1, priority: int = 2, dependencies: list[str] = None):
        self.id = f"task_{uuid.uuid4().hex[:8]}"
        self.service = service
        self.action = action
        self.params = params
        self.count = count
        self.priority = priority
        self.dependencies = dependencies or []
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service": self.service,
            "action": self.action,
            "count": self.count,
            "priority": self.priority,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class Batch:
    def __init__(self, tasks: list[Task]):
        self.id = f"batch_{uuid.uuid4().hex[:8]}"
        self.tasks = tasks
        self.created_at = datetime.now()

    @property
    def status(self) -> dict:
        total = len(self.tasks)
        counts = {s: 0 for s in TaskStatus}
        for t in self.tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        return {
            "batch_id": self.id,
            "total": total,
            "pending": counts[TaskStatus.PENDING],
            "running": counts[TaskStatus.RUNNING],
            "completed": counts[TaskStatus.COMPLETED],
            "failed": counts[TaskStatus.FAILED],
            "cancelled": counts[TaskStatus.CANCELLED],
            "progress": round(counts[TaskStatus.COMPLETED] / total * 100, 1) if total > 0 else 0,
        }


class TaskQueue:
    def __init__(self, max_concurrency: int = 3):
        self._batches: dict[str, Batch] = {}
        self._max_concurrency = max_concurrency
        self._running: set[str] = set()
        self._pending_queue: list[Task] = []
        self._on_complete = None

    def set_on_complete(self, handler):
        self._on_complete = handler

    def submit(self, tasks: list[Task]) -> str:
        batch = Batch(tasks)
        self._batches[batch.id] = batch
        for task in tasks:
            self._pending_queue.append(task)
        self._pending_queue.sort(key=lambda t: t.priority, reverse=False)
        return batch.id

    def get_batch(self, batch_id: str) -> Optional[Batch]:
        return self._batches.get(batch_id)

    def get_task(self, task_id: str) -> Optional[Task]:
        for batch in self._batches.values():
            for task in batch.tasks:
                if task.id == task_id:
                    return task
        return None

    def cancel_batch(self, batch_id: str):
        batch = self._batches.get(batch_id)
        if batch:
            for task in batch.tasks:
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    task.status = TaskStatus.CANCELLED
            self._pending_queue = [t for t in self._pending_queue if t not in batch.tasks]

    def pause_batch(self, batch_id: str):
        batch = self._batches.get(batch_id)
        if batch:
            for task in batch.tasks:
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED

    def get_status(self) -> dict:
        all_tasks = []
        for batch in self._batches.values():
            all_tasks.extend(batch.tasks)
        total = len(all_tasks)
        counts = {s.value: 0 for s in TaskStatus}
        for t in all_tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return {
            "total": total,
            "pending": counts["pending"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "cancelled": counts["cancelled"],
            "concurrency": self._max_concurrency,
        }

    async def process_loop(self):
        while True:
            available = self._max_concurrency - len(self._running)
            to_run = []
            remaining = []
            for task in self._pending_queue:
                if task.status != TaskStatus.PENDING:
                    continue
                if self._deps_met(task):
                    if len(to_run) < available:
                        to_run.append(task)
                    else:
                        remaining.append(task)
                else:
                    remaining.append(task)
            self._pending_queue = remaining + [t for t in self._pending_queue if t in to_run]

            for task in to_run:
                self._running.add(task.id)
                asyncio.create_task(self._execute(task))

            await asyncio.sleep(0.5)

    def _deps_met(self, task: Task) -> bool:
        for dep_id in task.dependencies:
            dep = self.get_task(dep_id)
            if dep and dep.status != TaskStatus.COMPLETED:
                return False
        return True

    async def _execute(self, task: Task):
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        try:
            result = await self._run_task(task)
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.result = result
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            task.completed_at = datetime.now()
            self._running.discard(task.id)
            if self._on_complete:
                await self._on_complete(task)

    async def _run_task(self, task: Task) -> Any:
        await asyncio.sleep(0.1 * task.count)
        return {"task_id": task.id, "status": "completed", "service": task.service, "action": task.action}
