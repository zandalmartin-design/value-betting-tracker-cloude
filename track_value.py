"""
track_value.py
Denně spusť tento skript (ručně, nebo naplánovaně přes Task Scheduler / cron).
Stáhne aktuální kurzy pro norskou a švédskou ligu, spočítá "férovou" pravděpodobnost
z Pinnacle (bez marže) a porovná ji s Unibet (SE) i s nejlepší cenou na trhu.
Každý běh přidá řádky do value_log.csv - nic nepřepisuje, jen přidává.
"""
import json
import csv
import os
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import HTTPError

# ---- NASTAVENÍ ----
# Klíč se čte z proměnné prostředí ODDS_API_KEY (bezpečnější než napsat ho do souboru).
# Pro lokální spuštění: buď proměnnou nastav, nebo dočasně nahraď řádek níže vlastním klíčem.
API_KEY = os.environ.get("ODDS_API_KEY", "VLOŽ_SEM_SVŮJ_KLÍČ")
LEAGUES = ["soccer_norway_eliteserien", "soccer_sweden_allsvenskan"]
REGIONS = "eu,uk"
LOG_FILE = "value_log.csv"
EDGE_THRESHOLD = 0.03  # od kolika % edge to považujeme za zajímavé (jen pro sloupec 'flag')

FIELDNAMES = [
    "fetched_at", "league", "match_id", "commence_time", "home_team", "away_team",
    "outcome", "pinnacle_odds", "pinnacle_fair_prob",
    "unibet_se_odds", "unibet_se_edge",
    "best_book", "best_odds", "best_edge", "flag"
]

def fetch_odds(sport_key):
    url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
           f"?regions={REGIONS}&markets=h2h&oddsFormat=decimal&apiKey={API_KEY}")
    try:
        with urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"Chyba při stahování {sport_key}: {e}")
        return []

def novig_probs(odds_dict):
    implied = {k: 1/v for k, v in odds_dict.items()}
    total = sum(implied.values())
    return {k: v/total for k, v in implied.items()}

def process_match(league, match):
    bookmakers = {b["key"]: b for b in match.get("bookmakers", [])}
    if "pinnacle" not in bookmakers:
        return []  # bez ostré reference to nemá cenu počítat

    pin_market = next((m for m in bookmakers["pinnacle"]["markets"] if m["key"] == "h2h"), None)
    if not pin_market:
        return []
    pin_odds = {o["name"]: o["price"] for o in pin_market["outcomes"]}
    fair = novig_probs(pin_odds)

    unibet_odds = {}
    if "unibet_se" in bookmakers:
        m = next((m for m in bookmakers["unibet_se"]["markets"] if m["key"] == "h2h"), None)
        if m:
            unibet_odds = {o["name"]: o["price"] for o in m["outcomes"]}

    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for outcome in pin_odds:
        # nejlepší kurz na trhu (kromě Pinnacle) pro tenhle výsledek
        best_book, best_price = None, 0
        for bkey, b in bookmakers.items():
            if bkey == "pinnacle":
                continue
            m = next((m for m in b["markets"] if m["key"] == "h2h"), None)
            if not m:
                continue
            for o in m["outcomes"]:
                if o["name"] == outcome and o["price"] > best_price:
                    best_price, best_book = o["price"], bkey

        unibet_price = unibet_odds.get(outcome)
        unibet_edge = (unibet_price * fair[outcome] - 1) if unibet_price else None
        best_edge = (best_price * fair[outcome] - 1) if best_price else None
        flag = "VALUE" if (unibet_edge and unibet_edge > EDGE_THRESHOLD) else ""

        rows.append({
            "fetched_at": now, "league": league, "match_id": match["id"],
            "commence_time": match["commence_time"],
            "home_team": match["home_team"], "away_team": match["away_team"],
            "outcome": outcome,
            "pinnacle_odds": pin_odds[outcome], "pinnacle_fair_prob": round(fair[outcome], 4),
            "unibet_se_odds": unibet_price, "unibet_se_edge": round(unibet_edge, 4) if unibet_edge else None,
            "best_book": best_book, "best_odds": best_price,
            "best_edge": round(best_edge, 4) if best_edge else None,
            "flag": flag,
        })
    return rows

def main():
    file_exists = os.path.exists(LOG_FILE)
    all_rows = []
    for league in LEAGUES:
        matches = fetch_odds(league)
        for match in matches:
            all_rows.extend(process_match(league, match))

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerows(all_rows)

    print(f"Zapsáno {len(all_rows)} řádků do {LOG_FILE}")
    flagged = [r for r in all_rows if r["flag"] == "VALUE"]
    if flagged:
        print(f"\n{len(flagged)} zápasů/výsledků označeno jako VALUE (edge > {EDGE_THRESHOLD*100:.0f}%):")
        for r in flagged:
            print(f"  {r['home_team']} vs {r['away_team']} - {r['outcome']}: "
                  f"Unibet {r['unibet_se_odds']} (edge {r['unibet_se_edge']*100:+.1f}%)")

if __name__ == "__main__":
    main()
