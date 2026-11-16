"""Open-Meteo /v1/forecast response (only the fields we request).

Field names from https://open-meteo.com/en/docs. Everything is optional and
unknown fields are ignored, so a partial answer still parses.
"""

from pydantic import BaseModel, ConfigDict


class _OpenMeteoModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CurrentWeather(_OpenMeteoModel):
    time: str | None = None
    interval: int | None = None
    temperature_2m: float | None = None
    weather_code: int | None = None


class DailyWeather(_OpenMeteoModel):
    time: list[str | None] | None = None
    temperature_2m_max: list[float | None] | None = None
    temperature_2m_min: list[float | None] | None = None
    precipitation_probability_max: list[float | None] | None = None


class Forecast(_OpenMeteoModel):
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    current: CurrentWeather | None = None
    daily: DailyWeather | None = None
