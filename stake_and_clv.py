"""
stake_and_clv.py
=================
Navazuje přímo na tvůj track_value.py a value_log.csv. Nic v track_value.py
se měnit nemusí - tenhle skript jen čte value_log.csv, který se ti tak jako
tak dennodenně plní novými řádky.

Dělá dvě věci:

1) STAKING - pro každou VALUE příležitost spočítá doporučenou sázku
   pomocí zlomkového Kelly (výchozí 1/4 Kelly - bezpečnější než plný Kelly).
   Výstup: staking_recommendations.csv

2) CLV REPORT - protože track_value.py běží opakovaně, máš pro každý
   zápas víc řádků v čase. Skript porovná kurz Unibet v okamžiku, kdy byl
   zápas poprvé označený jako VALUE, s posledním zaznamenaným kurzem před
   výkopem (closing line). Kladné CLV = vsadil jsi za lepší kurz, než byl
   na trhu na konci - to je nejrychlejší signál skutečné edge, rychlejší
   než čekání na dost vyhraných/prohraných tiketů.
   Výstup: přehled v terminálu.

Spouštění:
    python stake_and_clv.py stake     -> vygeneruje staking doporučení
    python stake_and_clv.py clv       -> vypíše CLV report
    python stake_and_clv.py           -> udělá obojí

Nastavení přes proměnné prostředí (stejný princip jako ODDS_API_KEY):
    BANKROLL_CZK      výchozí 10000
    KELLY_MULTIPLIER  výchozí 0.25 (čtvrtinový Kelly)
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VALUE_LOG = Path("value_log.csv")
STAKING_OUT = Path("staking_recommendations.csv")

BANKROLL_CZK = float(os.environ.get("BANKROLL_CZK", "10000"))
KELLY_MULTIPLIER = float(os.environ.get("KELLY_MULTIPLIER", "0.25"))


def kelly_stake_pct(fair_prob: float, decimal_odds: float, multiplier: float = KELLY_MULTIPLIER) -> float:
    """f* = (b*p - q) / b, pak vynásobeno zlomkem (multiplier).
    Vrací 0, pokud sázka nemá skutečnou edge (radši přeskočit než sázet naslepo)."""
    b = decimal_odds - 1
    q = 1 - fair_prob
    if b <= 0:
        return 0.0
    f_full = (b * fair_prob - q) / b
    return max(f_full * multiplier, 0.0)


def load_log() -> list[dict]:
    if not VALUE_LOG.exists():
        print(f"Nenašel jsem {VALUE_LOG} - spusť nejdřív track_value.py.")
        sys.exit(1)
    with VALUE_LOG.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def generate_staking_recommendations() -> None:
    rows = load_log()
    flagged = [r for r in rows if r.get("flag") == "VALUE" and r.get("unibet_se_odds")]

    # jen NEJSTARŠÍ výskyt každé (match_id, outcome) - to je okamžik, kdy jsi
    # sázku reálně mohl vsadit, ne pozdější přeceněný kurz
    first_seen = {}
    for r in flagged:
        key = (r["match_id"], r["outcome"])
        if key not in first_seen or r["fetched_at"] < first_seen[key]["fetched_at"]:
            first_seen[key] = r

    out_rows = []
    for r in first_seen.values():
        fair_prob = float(r["pinnacle_fair_prob"])
        odds = float(r["unibet_se_odds"])
        stake_pct = kelly_stake_pct(fair_prob, odds)
        out_rows.append({
            "match_id": r["match_id"],
            "league": r["league"],
            "commence_time": r["commence_time"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "outcome": r["outcome"],
            "odds_at_detection": odds,
            "fair_prob": round(fair_prob, 4),
            "edge_pct": round((fair_prob * odds - 1) * 100, 2),
            "kelly_stake_pct": round(stake_pct * 100, 2),
            "recommended_stake_czk": round(BANKROLL_CZK * stake_pct, 0),
        })

    with STAKING_OUT.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(out_rows[0].keys()) if out_rows else [
            "match_id", "league", "commence_time", "home_team", "away_team",
            "outcome", "odds_at_detection", "fair_prob", "edge_pct",
            "kelly_stake_pct", "recommended_stake_czk",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Zapsáno {len(out_rows)} doporučení do {STAKING_OUT}")
    for r in out_rows:
        print(f"  {r['home_team']} vs {r['away_team']} ({r['outcome']}): "
              f"kurz {r['odds_at_detection']}, edge {r['edge_pct']:+.1f}%, "
              f"sázka {r['recommended_stake_czk']:.0f} Kč "
              f"({r['kelly_stake_pct']:.1f}% bankrollu)")


def clv_report() -> None:
    rows = load_log()

    # seskup podle (match_id, outcome), seřaď podle času stažení
    by_match = defaultdict(list)
    for r in rows:
        if r.get("unibet_se_odds"):
            by_match[(r["match_id"], r["outcome"])].append(r)
    for key in by_match:
        by_match[key].sort(key=lambda r: r["fetched_at"])

    now = datetime.now(timezone.utc)
    clv_results = []

    for (match_id, outcome), history in by_match.items():
        first_value_row = next((r for r in history if r["flag"] == "VALUE"), None)
        if not first_value_row:
            continue  # tuhle sázku jsi nikdy neoznačil jako VALUE, přeskoč

        commence = datetime.fromisoformat(history[0]["commence_time"].replace("Z", "+00:00"))
        if commence > now:
            continue  # zápas ještě nezačal, closing odds ještě neznáme

        # poslední zaznamenaný kurz PŘED výkopem = closing line
        pre_kickoff = [r for r in history
                        if datetime.fromisoformat(r["fetched_at"].replace("Z", "+00:00")) < commence]
        if not pre_kickoff:
            continue
        closing_row = pre_kickoff[-1]

        odds_at_bet = float(first_value_row["unibet_se_odds"])
        closing_odds = float(closing_row["unibet_se_odds"])
        clv_pct = (odds_at_bet / closing_odds - 1) * 100

        clv_results.append({
            "match": f"{history[0]['home_team']} vs {history[0]['away_team']}",
            "outcome": outcome,
            "odds_at_bet": odds_at_bet,
            "closing_odds": closing_odds,
            "clv_pct": clv_pct,
        })

    if not clv_results:
        print("Zatím žádné odehrané zápasy s dost daty na CLV. "
              "Potřebuješ, aby track_value.py naběhl vícekrát před výkopem "
              "u stejného zápasu (ideálně denně).")
        return

    avg_clv = sum(r["clv_pct"] for r in clv_results) / len(clv_results)
    positive = sum(1 for r in clv_results if r["clv_pct"] > 0)

    print(f"CLV report - {len(clv_results)} vyhodnocených zápasů/výsledků\n")
    for r in clv_results:
        sign = "+" if r["clv_pct"] >= 0 else ""
        print(f"  {r['match']} ({r['outcome']}): sázka {r['odds_at_bet']}, "
              f"closing {r['closing_odds']}, CLV {sign}{r['clv_pct']:.2f}%")

    print(f"\nPrůměrné CLV:          {avg_clv:+.2f}%")
    print(f"% s kladným CLV:       {positive / len(clv_results) * 100:.1f}%")
    print()
    if len(clv_results) < 50:
        print("⚠️  Máš zatím < 50 vyhodnocených případů - na spolehlivý závěr")
        print("    je potřeba víc dat. Pokračuj ve sbírání.")
    elif avg_clv > 0 and positive / len(clv_results) > 0.55:
        print("✅ Konzistentně kladné CLV - silný signál, že máš skutečnou edge.")
    else:
        print("⚠️  CLV není konzistentně kladné - edge se zatím nepotvrzuje.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "both"
    if action == "stake":
        generate_staking_recommendations()
    elif action == "clv":
        clv_report()
    else:
        generate_staking_recommendations()
        print()
        clv_report()
