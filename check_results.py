"""
check_results.py
Spusť tenhle skript POTÉ, co odehrané zápasy skončí (klidně jednou týdně).
Projde value_log.csv, najde řádky označené jako VALUE, stáhne skutečné výsledky
a spočítá, jak by dopadlo sázení 1 jednotky na každou z nich.
"""
import json
import csv
import os
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import HTTPError

API_KEY = os.environ.get("ODDS_API_KEY", "VLOŽ_SEM_SVŮJ_KLÍČ")
LOG_FILE = "value_log.csv"
LEAGUES = ["soccer_norway_eliteserien", "soccer_sweden_allsvenskan"]

def fetch_scores(sport_key, days_from=3):
    url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"
           f"?daysFrom={days_from}&apiKey={API_KEY}")
    try:
        with urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"Chyba při stahování výsledků {sport_key}: {e}")
        return []

def main():
    with open(LOG_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    flagged = [r for r in rows if r["flag"] == "VALUE"]
    print(f"Nalezeno {len(flagged)} označených sázek v logu.")

    # stáhni výsledky pro obě ligy, slož do slovníku match_id -> výsledek
    results = {}
    for league in LEAGUES:
        scores = fetch_scores(league, days_from=3)
        for m in scores:
            if m.get("completed"):
                results[m["id"]] = m

    stake, profit, n_resolved, n_won = 0, 0, 0, 0
    print("\n--- Vyhodnocené sázky ---")
    for r in flagged:
        match = results.get(r["match_id"])
        if not match:
            continue  # zápas ještě neproběhl / výsledek zatím není k dispozici
        scores = {s["name"]: int(s["score"]) for s in match["scores"]}
        home, away = match["home_team"], match["away_team"]
        if scores[home] > scores[away]:
            winner = home
        elif scores[away] > scores[home]:
            winner = away
        else:
            winner = "Draw"

        won = (r["outcome"] == winner)
        odd = float(r["unibet_se_odds"])
        stake += 1
        n_resolved += 1
        if won:
            profit += (odd - 1)
            n_won += 1
        else:
            profit -= 1
        print(f"  {home} vs {away} - sázka na '{r['outcome']}' @ {odd}: "
              f"{'VYHRÁLA' if won else 'prohrála'} (výsledek: {winner})")

    print(f"\n=== Souhrn ===")
    print(f"Vyhodnoceno: {n_resolved} z {len(flagged)} označených sázek")
    if stake:
        print(f"Úspěšnost: {n_won}/{n_resolved} ({n_won/n_resolved*100:.1f}%)")
        print(f"Zisk/ztráta: {profit:.2f} jednotek, ROI: {profit/stake*100:.2f}%")
    else:
        print("Zatím žádné vyhodnocené sázky - zápasy ještě neproběhly nebo výsledky nejsou dostupné.")

if __name__ == "__main__":
    main()
