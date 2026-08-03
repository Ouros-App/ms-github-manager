from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    organization: str
    default_branch: str
