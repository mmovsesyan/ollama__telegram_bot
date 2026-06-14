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
                f"{emoji} Погода в {area_name}" + (f", {country}\n" if country else "\n")
                + (f"{emoji} {desc}\n" if desc else "")
                + f"🌡 Температура: {temp}°C (ощущается {feels}°C)\n"
                f"💨 Ветер: {wind} km/h {wind_dir}\n"
                f"💧 Влажность: {humidity}%\n"
                f"📊 Давление: {pressure} мм рт. ст.\n"
                f"👁 Видимость: {visibility} км\n\n"
                f"Источник: wttr.in"
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
            wind_dir = cur.get("wind_direction_10m", "")
            pressure = cur.get("pressure_msl", "?")
            code = cur.get("weather_code", 0)
            wmo_desc = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Fog", 48: "Depositing rime fog",
                51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
            }
            desc = wmo_desc.get(code, "Unknown")
            emoji = _weather_emoji(desc)
            text = (
                f"{emoji} Погода в {name}" + (f", {country}\n" if country else "\n")
                + (f"{emoji} {desc}\n" if desc else "")
                + f"🌡 Температура: {temp}°C (ощущается {feels}°C)\n"
                f"💨 Ветер: {wind} km/h {wind_dir}\n"
                f"💧 Влажность: {humidity}%\n"
                f"📊 Давление: {pressure} гПа\n\n"
                f"Источник: Open-Meteo"
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
