from fastapi import Request

from app.services.demo_service import DemoService
from app.services.task_service import TaskService


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service


def get_demo_service(request: Request) -> DemoService:
    return request.app.state.demo_service
