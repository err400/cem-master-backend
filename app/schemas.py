from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpotCreate(BaseModel):
    source_project_id: str = Field(..., max_length=120)
    source_spot_id: str = Field(..., max_length=120)
    name: str = Field(..., max_length=200)
    description: str | None = None
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    @field_validator("source_project_id", "source_spot_id", "name")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SpotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_project_id: str
    source_spot_id: str
    name: str
    description: str | None
    latitude: float
    longitude: float
