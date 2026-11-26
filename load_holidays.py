"""공휴일 JSON(holidays_2026_2027.json)을 Supabase holidays 테이블에 한 번 넣습니다.

사용법: 공휴일 테스트 때 저장한 holidays_2026_2027.json을 이 파일과 같은 폴더에 두고
    py load_holidays.py
"""
import json

from db import load_env, upsert

load_env()

with open("holidays_2026_2027.json", encoding="utf-8") as f:
    holidays = json.load(f)

rows = {h["date"]: {"date": h["date"], "name": h["name"], "is_holiday": h["is_holiday"]}
        for h in holidays}
print("holidays", upsert("holidays", list(rows.values()), ["date"]), "행 저장")
