"""Open-Meteo provider for the weather card. Docs: https://open-meteo.com/en/docs"""

import httpx2

from app.config import Settings
from app.schemas.briefing import WeatherSection
from app.schemas.weather import Forecast
from app.services.cache import TTLCache

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# "WMO Weather interpretation codes", copied from the Open-Meteo docs.
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    97: "Heavy thunderstorm",
    99: "Thunderstorm with heavy hail",
}

_cache = TTLCache("weather")


def fetch_forecast(client: httpx2.Client, settings: Settings) -> Forecast:
    params = {
        "latitude": settings.weather_latitude,
        "longitude": settings.weather_longitude,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": settings.weather_timezone,  # required when `daily` is requested
        "forecast_days": 1,
    }
    response = client.get(FORECAST_URL, params=params)
    response.raise_for_status()
    return Forecast.model_validate(response.json())


def _first(values: list | None):
    return values[0] if values else None


def describe(forecast: Forecast) -> list[str]:
    """Turn a forecast into display lines; missing values are left out."""
    lines: list[str] = []

    current = forecast.current
    if current and current.temperature_2m is not None:
        line = f"{current.temperature_2m:.0f} °C"
        condition = WMO_CODES.get(current.weather_code) if current.weather_code is not None else None
        if condition:
            line += f", {condition}"
        lines.append(line)

    daily = forecast.daily
    if daily:
        t_min = _first(daily.temperature_2m_min)
        t_max = _first(daily.temperature_2m_max)
        rain = _first(daily.precipitation_probability_max)
        parts = []
        if t_min is not None and t_max is not None:
            parts.append(f"Today {t_min:.0f}–{t_max:.0f} °C")
        if rain is not None:
            parts.append(f"rain chance {rain:.0f} %")
        if parts:
            lines.append(" · ".join(parts))

    return lines


def get_weather_section(client: httpx2.Client, settings: Settings) -> WeatherSection:
    """Raises on HTTP/parse errors; the briefing turns that into "unavailable"."""
    key = (settings.weather_latitude, settings.weather_longitude, settings.weather_timezone)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    section = WeatherSection.from_items(describe(fetch_forecast(client, settings)))
    _cache.set(key, section, settings.cache_ttl_weather)
    return section
