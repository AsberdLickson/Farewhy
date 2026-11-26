"""Supabase(REST) 저장 헬퍼와 환경변수 로더. 추가 패키지 없이 requests만 사용합니다."""
import os
import requests


def load_env(path=".env"):
    """로컬 실행용: .env 파일의 KEY=VALUE를 환경변수로 읽어 옵니다.
    GitHub Actions에서는 Secrets가 환경변수로 들어오므로 파일이 없어도 됩니다."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"환경변수 {name}가 비어 있습니다 (.env 또는 GitHub Secrets 확인)")
    return value


def _headers(prefer):
    key = env("SUPABASE_KEY")
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    # 예전 형식 키(service_role, eyJ...로 시작)는 Authorization 헤더도 필요합니다.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def insert(table, rows):
    """행을 그대로 추가합니다 (스냅샷용)."""
    if not rows:
        return 0
    url = f"{env('SUPABASE_URL').rstrip('/')}/rest/v1/{table}"
    r = requests.post(url, json=rows, headers=_headers("return=minimal"), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"{table} 저장 실패 {r.status_code}: {r.text[:300]}")
    return len(rows)


def upsert(table, rows, conflict_cols):
    """같은 키가 있으면 덮어씁니다 (가격 이력·환율·공휴일용)."""
    if not rows:
        return 0
    url = f"{env('SUPABASE_URL').rstrip('/')}/rest/v1/{table}"
    r = requests.post(
        url,
        params={"on_conflict": ",".join(conflict_cols)},
        json=rows,
        headers=_headers("resolution=merge-duplicates,return=minimal"),
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"{table} 저장 실패 {r.status_code}: {r.text[:300]}")
    return len(rows)
