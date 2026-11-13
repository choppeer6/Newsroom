from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar

from app.agents.contracts import AgentInput, AgentOutput
from app.schemas.enums import AgentName

InputT = TypeVar("InputT", bound=AgentInput)
OutputT = TypeVar("OutputT", bound=AgentOutput)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    name: ClassVar[AgentName]

    @abstractmethod
    async def run(self, payload: InputT) -> OutputT:
        raise NotImplementedError
