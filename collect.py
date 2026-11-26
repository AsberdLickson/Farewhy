"""가격·인사이트·환율 수집 스크립트.

사용법
    py collect.py               # 자동: 한국 시간 12시 이후면 전체, 이전이면 가볍게
    py collect.py --mode light  # Travelpayouts 가격만 (SerpApi 횟수 안 씀)
    py collect.py --mode full   # 전체 (SerpApi 6회 사용)

GitHub Actions는 하루 2번(한국 09시·21시) 실행합니다.
  09시 → light: Travelpayouts 가격만
  21시 → full : + SerpApi 인사이트·가격 이력 + 환율(수출입은행은 11시 이후 갱신)
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from db import env, insert, load_env, upsert

KST = timezone(timedelta(hours=9))

# 노선 설정 ------------------------------------------------------------------
# tp    : Travelpayouts 도착 코드 (도시 코드라 여러 공항 포함)
# serp  : SerpApi 도착 공항 (왕복 인사이트가 나오는 것을 확인한 공항)
# fx    : 설명에 쓸 통화 (동·대만달러는 수출입은행에 없어 USD로 대체)
ROUTES = [
    {"route": "ICN-TYO", "tp": "TYO", "serp": "NRT", "fx": "JPY(100)"},
    {"route": "ICN-OSA", "tp": "OSA", "serp": "KIX", "fx": "JPY(100)"},
    {"route": "ICN-FUK", "tp": "FUK", "serp": "FUK", "fx": "JPY(100)"},
    {"route": "ICN-TPE", "tp": "TPE", "serp": "TPE", "fx": "USD"},
    {"route": "ICN-BKK", "tp": "BKK", "serp": "BKK", "fx": "THB"},
    {"route": "ICN-DAD", "tp": "DAD", "serp": "DAD", "fx": "USD"},
]

# Travelpayouts에서 조회할 출발 월
TP_MONTHS = ["2026-12", "2027-01", "2027-02"]

# SerpApi는 노선마다 이 왕복 일정 하나를 매일 같은 조건으로 조회합니다.
# 조건이 매일 같아야 인사이트를 날짜별로 비교할 수 있으니 중간에 바꾸지 마세요.
SERP_OUTBOUND = "2026-12-26"
SERP_RETURN = "2026-12-30"

FX_KEEP = {"JPY(100)", "THB", "USD"}


# Travelpayouts ---------------------------------------------------------------
def collect_travelpayouts():
    token = env("TP_TOKEN")
    rows = []
    for r in ROUTES:
        for month in TP_MONTHS:
            resp = requests.get(
                "https://api.travelpayouts.com/aviasales/v3/prices_for_dates",
                headers={"X-Access-Token": token},
                params={
                    "origin": "ICN",
                    "destination": r["tp"],
                    "departure_at": month,
                    "one_way": "true",
                    "currency": "krw",
                    "sorting": "price",
                    "limit": 30,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                print(f"  [TP] {r['route']} {month} 실패: {data}")
                continue
            for f in data.get("data", []):
                rows.append({
                    "route": r["route"],
                    "origin_airport": f.get("origin_airport"),
                    "destination_airport": f.get("destination_airport"),
                    "departure_at": f.get("departure_at"),
                    "airline": f.get("airline"),
                    "flight_number": str(f.get("flight_number") or ""),
                    "price": int(f["price"]),
                    "transfers": f.get("transfers"),
                    "gate": f.get("gate"),
                })
            time.sleep(0.5)
    n = insert("prices", rows)
    print(f"  [TP] prices {n}행 저장")


# SerpApi ---------------------------------------------------------------------
def collect_serpapi():
    key = env("SERPAPI_KEY")
    insight_rows, history_rows = [], []
    for r in ROUTES:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_flights",
                "departure_id": "ICN",
                "arrival_id": r["serp"],
                "outbound_date": SERP_OUTBOUND,
                "return_date": SERP_RETURN,
                "type": "1",            # 왕복 (편도는 인사이트가 비어 옴)
                "currency": "KRW",
                "hl": "ko",
                "api_key": key,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"  [SERP] {r['route']} 오류: {data['error']}")
            continue
        pi = data.get("price_insights")
        if not pi:
            print(f"  [SERP] {r['route']} 인사이트 없음 (항공편 {len(data.get('other_flights', []))}개)")
            continue

        typical = pi.get("typical_price_range") or [None, None]
        insight_rows.append({
            "route": r["route"],
            "outbound_date": SERP_OUTBOUND,
            "return_date": SERP_RETURN,
            "lowest_price": pi.get("lowest_price"),
            "price_level": pi.get("price_level"),
            "typical_low": typical[0],
            "typical_high": typical[1],
        })

        # 같은 날짜가 두 번 들어오면 upsert가 실패하므로 날짜별로 하나만 남깁니다.
        by_date = {}
        for ts, price in pi.get("price_history") or []:
            if ts > 10**11:          # 밀리초로 오는 경우 대비
                ts //= 1000
            d = datetime.fromtimestamp(ts, KST).date().isoformat()
            by_date[d] = price
        for d, price in by_date.items():
            history_rows.append({
                "route": r["route"],
                "outbound_date": SERP_OUTBOUND,
                "return_date": SERP_RETURN,
                "date": d,
                "price": int(price),
            })
        time.sleep(1)

    print(f"  [SERP] price_insights {insert('price_insights', insight_rows)}행 저장")
    n = upsert("price_history", history_rows, ["route", "outbound_date", "return_date", "date"])
    print(f"  [SERP] price_history {n}행 저장(덮어쓰기 포함)")


# 수출입은행 환율 --------------------------------------------------------------
def collect_fx():
    today = datetime.now(KST).date()
    resp = requests.get(
        "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON",
        params={"authkey": env("EXIM_KEY"), "searchdate": today.strftime("%Y%m%d"), "data": "AP01"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        print("  [FX] 오늘 환율 없음 (주말·공휴일이거나 11시 이전) → 건너뜀")
        return
    rows = [
        {"date": today.isoformat(),
         "currency": x["cur_unit"],
         "rate": float(x["deal_bas_r"].replace(",", ""))}
        for x in data
        if x.get("cur_unit") in FX_KEEP
    ]
    print(f"  [FX] fx_rates {upsert('fx_rates', rows, ['date', 'currency'])}행 저장")


# 실행 -------------------------------------------------------------------------
def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "light", "full"], default="auto")
    mode = parser.parse_args().mode
    if mode == "auto":
        mode = "full" if datetime.now(KST).hour >= 12 else "light"

    print(f"수집 시작 {datetime.now(KST):%Y-%m-%d %H:%M} KST, 모드: {mode}")
    jobs = [("Travelpayouts", collect_travelpayouts)]
    if mode == "full":
        jobs += [("SerpApi", collect_serpapi), ("환율", collect_fx)]

    failed = []
    for name, job in jobs:
        try:
            job()
        except Exception as e:      # 한 소스가 실패해도 나머지는 계속 수집
            print(f"  [{name}] 실패: {e}")
            failed.append(name)

    if failed:
        print("실패한 소스:", ", ".join(failed))
        sys.exit(1)                 # GitHub Actions에 빨간불로 표시
    print("완료")


if __name__ == "__main__":
    main()
