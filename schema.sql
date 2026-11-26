-- 언제살래(FareWhy) 테이블 생성
-- Supabase 대시보드 > SQL Editor에 전체를 붙여 넣고 Run

-- 1) Travelpayouts 항공권 가격 스냅샷 (하루 2회 쌓임)
create table if not exists prices (
    id                  bigserial primary key,
    collected_at        timestamptz not null default now(),
    route               text not null,          -- 예: ICN-TYO
    origin_airport      text,
    destination_airport text,
    departure_at        timestamptz,
    airline             text,
    flight_number       text,
    price               integer not null,       -- 원(KRW), 편도
    transfers           integer,
    gate                text                    -- 판매처 (Trip.com 등)
);
create index if not exists prices_route_dep_idx on prices (route, departure_at);
create index if not exists prices_collected_idx on prices (collected_at);

-- 2) SerpApi 구글 가격 인사이트 (하루 1회)
create table if not exists price_insights (
    id            bigserial primary key,
    collected_at  timestamptz not null default now(),
    route         text not null,
    outbound_date date not null,
    return_date   date not null,
    lowest_price  integer,
    price_level   text,                         -- low / typical / high
    typical_low   integer,
    typical_high  integer
);
create index if not exists insights_route_idx on price_insights (route, collected_at);

-- 3) SerpApi 가격 이력 (호출마다 약 60일치, 중복은 덮어씀)
create table if not exists price_history (
    route         text not null,
    outbound_date date not null,
    return_date   date not null,
    date          date not null,                -- 이 날짜의 가격 (한국 시간 기준)
    price         integer not null,
    primary key (route, outbound_date, return_date, date)
);

-- 4) 수출입은행 환율 (영업일 1회)
create table if not exists fx_rates (
    date     date not null,
    currency text not null,                     -- JPY(100), THB, USD
    rate     numeric not null,                  -- 매매기준율 (원)
    primary key (date, currency)
);

-- 5) 공휴일 (한 번만 적재)
create table if not exists holidays (
    date       date primary key,
    name       text not null,
    is_holiday boolean not null default true
);

-- 외부(anon 키)에서 함부로 읽고 쓰지 못하게 RLS를 켭니다.
-- 수집 스크립트는 secret(service_role) 키를 쓰므로 영향받지 않습니다.
alter table prices         enable row level security;
alter table price_insights enable row level security;
alter table price_history  enable row level security;
alter table fx_rates       enable row level security;
alter table holidays       enable row level security;
