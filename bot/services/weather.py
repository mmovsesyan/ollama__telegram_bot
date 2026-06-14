"""Weather lookup with wttr.in primary and Open-Meteo fallback."""

import json
import aiohttp


def _weather_emoji(desc: str) -> str:
    d = desc.lower()
    if "thunder" in d or "storm" in d:
        return "⛈️"
    if "snow" in d or "sleet" in d or "blizzard" in d or "ice" in d:
        return "❄️"
    if "rain" in d or "drizzle" in d or "shower" in d:
        return "🌧️"
    if "clear" in d or "sunny" in d:
        return "☀️"
    if "partly" in d:
        return "⛅"
    if "cloud" in d or "overcast" in d:
        return "☁️"
    if "fog" in d or "mist" in d or "haze" in d:
        return "🌫️"
    if "wind" in d or "breeze" in d:
        return "💨"
    return "🌡️"


async def _get_wttr(city: str) -> tuple[str | None, str | None]:
    async with aiohttp.ClientSession() as session:
        url = f"https://wttr.in/{city}?format=j1"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None, f"Invalid JSON from wttr.in: {text[:200]}"
            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            area_name = area.get("areaName", [{}])[0].get("value", city)
            country = area.get("country", [{}])[0].get("value", "")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            emoji = _weather_emoji(desc)
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            wind = current.get("windspeedKmph", "?")
            wind_dir = current.get("winddir16Point", "")
            humidity = current.get("humidity", "?")
            pressure = current.get("pressure", "?")
            visibility = current.get("visibility", "?")
            text = (
                f"{emoji} {area_name}" + (f", {country}\n" if country else "\n")
                + (f"{desc}\n" if desc else "")
                + f"🌡 {temp}° (ощущается {feels}°)\n"
                f"💨 {wind} км/ч{f' {wind_dir}' if wind_dir else ''}   "
                f"💦 {humidity}%   "
                f"📊 {pressure} мм\n"
                f"\nИсточник: wttr.in"
            )
            return text, None


async def _get_open_meteo(city: str) -> tuple[str | None, str | None]:
    async with aiohttp.ClientSession() as session:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru"
        async with session.get(geo_url, timeout=aiohttp.ClientTimeout(total=10)) as geo_resp:
            if geo_resp.status != 200:
                return None, f"Geocoding HTTP {geo_resp.status}"
            geo = await geo_resp.json()
            results = geo.get("results", [])
            if not results:
                return None, "Город не найден"
            loc = results[0]
            lat = loc["latitude"]
            lon = loc["longitude"]
            name = loc.get("name", city)
            country = loc.get("country", "")

        w_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current="
            f"temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
            f"wind_speed_10m,wind_direction_10m,pressure_msl"
        )
        async with session.get(w_url, timeout=aiohttp.ClientTimeout(total=10)) as w_resp:
            if w_resp.status != 200:
                return None, f"Weather HTTP {w_resp.status}"
            w = await w_resp.json()
            cur = w.get("current", {})
            temp = cur.get("temperature_2m", "?")
            feels = cur.get("apparent_temperature", "?")
            humidity = cur.get("relative_humidity_2m", "?")
            wind = cur.get("wind_speed_10m", "?")
            pressure = cur.get("pressure_msl", "?")
            code = cur.get("weather_code", 0)
            desc = _WMO_DESC.get(code, "")
            emoji = _wmo_emoji(code)
            text = (
                f"{emoji} {name}" + (f", {country}\n" if country else "\n")
                + (f"{desc.lower()}\n" if desc else "")
                + f"🌡 {temp}° (ощущается {feels}°)\n"
                f"💨 {wind} км/ч   "
                f"💦 {humidity}%   "
                f"📊 {pressure} гПа\n"
                f"\nИсточник: Open-Meteo"
            )
            return text, None


async def get_weather(city: str) -> tuple[str | None, str | None]:
    """Try wttr.in, fall back to Open-Meteo."""
    try:
        text, error = await _get_wttr(city)
        if text:
            return text, None
    except Exception as e:
        print(f"[WEATHER] wttr.in failed: {e}, trying fallback")
    try:
        return await _get_open_meteo(city)
    except Exception as e:
        return None, str(e)[:200]


_WMO_DESC = {
    0: "Ясно", 1: "Преимущественно ясно", 2: "Переменная облачность", 3: "Пасмурно",
    45: "Туман", 48: "Изморозь",
    51: "Слабая морось", 53: "Морось", 55: "Сильная морось",
    61: "Слабый дождь", 63: "Дождь", 65: "Сильный дождь",
    71: "Слабый снег", 73: "Снег", 75: "Сильный снег",
    77: "Снежная крупа",
    80: "Кратковременный дождь", 81: "Ливень", 82: "Сильный ливень",
    85: "Кратковременный снег", 86: "Сильный снег",
    95: "Гроза", 96: "Гроза с градом", 99: "Сильная гроза с градом",
}


def _wmo_emoji(code: int) -> str:
    """Pick an emoji from a WMO weather code without relying on the
    English-keyword matcher."""
    if code == 0:
        return "☀️"
    if code in (1, 2):
        return "⛅"
    if code == 3:
        return "☁️"
    if code in (45, 48):
        return "🌫️"
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return "🌧️"
    if code in (71, 73, 75, 77, 85, 86):
        return "❄️"
    if code in (95, 96, 99):
        return "⛈️"
    return "🌡️"

_RU_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _days_word(n: int) -> str:
    """Russian plural for день/дня/дней."""
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


async def _forecast_open_meteo(city: str, days: int) -> tuple[str | None, str | None]:
    """Daily forecast for `days` days (max 16). Min/max temp, precip,
    wind, humidity per day. Open-Meteo, no API key."""
    days = max(1, min(days, 16))
    async with aiohttp.ClientSession() as session:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru"
        async with session.get(geo_url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return None, f"Geocoding HTTP {r.status}"
            geo = await r.json()
            results = geo.get("results", [])
            if not results:
                return None, "Город не найден"
            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            name = loc.get("name", city)
            country = loc.get("country", "")
            tz = loc.get("timezone", "auto")

        url = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&forecast_days={days}&timezone={tz}"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max,"
            "wind_speed_10m_max,relative_humidity_2m_mean"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                return None, f"Forecast HTTP {r.status}"
            data = await r.json()

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return None, "Нет данных прогноза"

    from datetime import date
    location = name + (f", {country}" if country else "")
    lines = [f"📅 {location} — {len(dates)} {_days_word(len(dates))}", ""]
    for i, ds in enumerate(dates):
        try:
            d = date.fromisoformat(ds)
            label = f"{_RU_WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}"
        except Exception:
            label = ds
        code = daily.get("weather_code", [0])[i]
        desc = _WMO_DESC.get(code, "")
        emoji = _wmo_emoji(code)
        tmax = daily.get("temperature_2m_max", [None])[i]
        tmin = daily.get("temperature_2m_min", [None])[i]
        pprob = daily.get("precipitation_probability_max", [0])[i] or 0
        # Show precipitation chance only when meaningful, otherwise drop it.
        suffix = f" {pprob:.0f}%" if pprob >= 30 else ""
        temp = f"{tmin:.0f}…{tmax:.0f}°" if tmin is not None and tmax is not None else "—"
        lines.append(f"{emoji} {label}   {temp}   {desc.lower()}{suffix}")
    lines.append("")
    lines.append("Источник: Open-Meteo")
    return "\n".join(lines), None


async def _forecast_wttr(city: str, days: int) -> tuple[str | None, str | None]:
    """wttr.in fallback. Capped at 3 days — that's all the j1 endpoint
    returns. Less detail than Open-Meteo but useful when api.open-meteo.com
    is slow or down."""
    days = max(1, min(days, 3))
    async with aiohttp.ClientSession() as session:
        url = f"https://wttr.in/{city}?format=j1"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None, "Invalid JSON"

    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city)
    country = area.get("country", [{}])[0].get("value", "")
    forecast = data.get("weather", [])[:days]
    if not forecast:
        return None, "Нет данных прогноза"

    from datetime import date
    location = name + (f", {country}" if country else "")
    lines = [f"📅 {location} — {len(forecast)} {_days_word(len(forecast))}", ""]
    for day in forecast:
        ds = day.get("date", "")
        try:
            d = date.fromisoformat(ds)
            label = f"{_RU_WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}"
        except Exception:
            label = ds
        tmax = day.get("maxtempC", "?")
        tmin = day.get("mintempC", "?")
        hourly = day.get("hourly", [])
        mid = hourly[len(hourly) // 2] if hourly else {}
        desc = (mid.get("weatherDesc") or [{}])[0].get("value", "")
        emoji = _weather_emoji(desc.lower())
        try:
            rain_chance = int(mid.get("chanceofrain", "0") or 0)
        except (TypeError, ValueError):
            rain_chance = 0
        suffix = f" {rain_chance}%" if rain_chance >= 30 else ""
        lines.append(f"{emoji} {label}   {tmin}…{tmax}°   {desc.lower()}{suffix}")
    lines.append("")
    lines.append("Источник: wttr.in")
    return "\n".join(lines), None


async def get_forecast(city: str, days: int = 7) -> tuple[str | None, str | None]:
    """Multi-day forecast. Open-Meteo first (up to 16 days, detailed
    payload), wttr.in fallback (3 days max) when Open-Meteo is slow."""
    try:
        text, error = await _forecast_open_meteo(city, days)
        if text:
            return text, None
        last_err = error
    except Exception as e:
        last_err = str(e)[:200]
        print(f"[FORECAST] Open-Meteo failed: {last_err}, trying wttr.in")
    try:
        return await _forecast_wttr(city, days)
    except Exception as e:
        return None, last_err or str(e)[:200]
