"""Lager et realistisk MET-svar for tester (og for lokal etterligning av MET)."""
from datetime import datetime, timedelta, timezone


def make_sample(start: datetime, hourly_hours: int = 48, six_hourly_days: int = 5) -> dict:
    """Timesvarsel i `hourly_hours` timer, deretter 6-timersvarsel."""
    series = []
    codes = ["clearsky_day", "partlycloudy_day", "cloudy", "lightrain", "rain", "fair_night"]
    t = start.replace(minute=0, second=0, microsecond=0)
    for i in range(hourly_hours):
        hour = t + timedelta(hours=i)
        temp = 10 + 5 * ((i % 24) / 24)
        data = {
            "instant": {"details": {"air_temperature": round(temp, 1), "wind_speed": 3.0 + (i % 5),
                                    "wind_from_direction": (i * 30) % 360, "relative_humidity": 70.0}},
            "next_1_hours": {"summary": {"symbol_code": codes[i % len(codes)]},
                             "details": {"precipitation_amount": 0.5 if i % 4 == 0 else 0.0}},
        }
        if hour.hour % 6 == 0:
            data["next_6_hours"] = {"summary": {"symbol_code": "rain" if i % 12 == 0 else "partlycloudy_day"},
                                    "details": {"precipitation_amount": 2.0, "air_temperature_max": round(temp + 2, 1),
                                                "air_temperature_min": round(temp - 3, 1)}}
        series.append({"time": hour.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data})
    t6 = t + timedelta(hours=hourly_hours)
    for i in range(six_hourly_days * 4):
        hour = t6 + timedelta(hours=6 * i)
        series.append({"time": hour.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {
            "instant": {"details": {"air_temperature": 8.0 + i % 4, "wind_speed": 5.0, "wind_from_direction": 200}},
            "next_6_hours": {"summary": {"symbol_code": "snow"},
                             "details": {"precipitation_amount": 1.0, "air_temperature_max": 9.0, "air_temperature_min": 4.0}},
        }})
    return {"type": "Feature", "properties": {"meta": {"updated_at": start.isoformat()}, "timeseries": series}}


if __name__ == "__main__":
    import json
    print(json.dumps(make_sample(datetime.now(timezone.utc) - timedelta(hours=1))))
