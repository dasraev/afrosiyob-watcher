#!/usr/bin/env python3
"""Watch ALL Afrosiyob trains Navoiy -> Toshkent on the given dates; Telegram alert when seats appear.
Env: TG_TOKEN, TG_CHAT_ID. Optional: MAX_MINUTES (stop after N minutes), INTERVAL (seconds)."""
import http.cookiejar, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://eticket.uzrailpass.uz"
DEP, ARV = "2900930", "2900000"            # Navoiy -> Toshkent
DATES = ["2026-10-08", "2026-10-09"]
BRAND = "Afrosiyob"
INTERVAL = int(os.environ.get("INTERVAL", 30))
MAX_MINUTES = float(os.environ.get("MAX_MINUTES", 0)) or None
TZ = timezone(timedelta(hours=5))          # Uzbekistan time

TOKEN, CHAT = os.environ["TG_TOKEN"], os.environ["TG_CHAT_ID"]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36",
      "Accept": "application/json", "device-type": "BROWSER", "Accept-Language": "uz",
      "Origin": BASE, "Referer": BASE + "/uz/pages/trains-page"}


def send(text):
    try:
        data = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=30).read()
    except Exception as e:
        print("telegram error:", e, flush=True)


def xsrf():
    for _ in range(2):
        for c in jar:
            if c.name == "XSRF-TOKEN":
                return urllib.parse.unquote(c.value)
        opener.open(urllib.request.Request(BASE + "/api/v1/csrf-token", headers=UA), timeout=30).read()
    return ""


def trains(date):
    body = json.dumps({"directions": {"forward": {"date": date, "depStationCode": DEP, "arvStationCode": ARV}},
                       "routeType": "INTERCITY"}).encode()
    req = urllib.request.Request(BASE + "/api/v3/handbook/trains/list", data=body, method="POST",
                                 headers={**UA, "Content-Type": "application/json",
                                          "X-XSRF-TOKEN": xsrf(), "X-Custom-Language": "uz"})
    return json.loads(opener.open(req, timeout=30).read())["data"]["directions"]["forward"]["trains"]


def describe(cars):
    out = []
    for c in cars:
        prices = sorted({t["tariff"] for t in c.get("tariffs", []) if t.get("tariff")})
        out.append(f'  {c["type"]}: {c["freeSeats"]} seats' + (f' (from {prices[0]:,} so\'m)'.replace(",", " ") if prices else ""))
    return "\n".join(out)


def scan():
    """Return {train_key: (seats, text)} for upcoming Afrosiyob trains."""
    now = datetime.now(TZ)
    found = {}
    for d in DATES:
        for t in trains(d):
            if t.get("brand") != BRAND:
                continue
            dep = datetime.strptime(t["departureDate"], "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
            if dep < now:
                continue
            cars = t.get("cars") or []
            seats = sum(c.get("freeSeats", 0) for c in cars)
            key = f'{t["number"]} {t["departureDate"]}'
            found[key] = (seats, f'🚆 {BRAND} {t["number"]}  {t["departureDate"]} → {t["arrivalDate"][-5:]}\n{describe(cars)}')
    return found


start, prev, errors, last_departure = time.time(), {}, 0, None
first = True
while True:
    now = datetime.now(TZ).strftime("%d.%m %H:%M:%S")
    try:
        cur = scan()
        errors = 0
        avail = {k: v for k, v in cur.items() if v[0] > 0}
        print(f"[{now}] {len(cur)} upcoming Afrosiyob, with seats: {list(avail) or 'none'}", flush=True)
        if first:
            print("trains:", list(cur), flush=True)
        new = [v[1] for k, v in avail.items() if prev.get(k, 0) == 0]
        if new:
            send("SEATS AVAILABLE — Navoiy → Toshkent\n\n" + "\n\n".join(new) + f"\n\nBuy: {BASE}/uz/pages/trains-page")
        gone = [k for k, s in prev.items() if s > 0 and cur.get(k, (0,))[0] == 0]
        if gone:
            send("⚠️ Sold out again: " + ", ".join(gone) + ". Still watching.")
        prev = {k: v[0] for k, v in cur.items()}
        first = False
        if not cur:
            print("No upcoming Afrosiyob trains left — done.", flush=True)
            send("All Afrosiyob trains for 8–9 Oct have departed. Watcher stopped.")
            open("DONE", "w").write("done")
            break
    except Exception as e:
        errors += 1
        jar.clear()
        print(f"[{now}] error: {e}", flush=True)
        if errors == 10:
            send(f"⚠️ Train watcher: 10 checks in a row failed ({e}).")
    if "--once" in sys.argv or (MAX_MINUTES and time.time() - start > MAX_MINUTES * 60):
        break
    time.sleep(INTERVAL)
