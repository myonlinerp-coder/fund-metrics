"""
Fund metrics calculator (uses only Python standard library).
Run:  python fund_metrics.py
Output: fund_metrics.csv  (upload this file back to Claude to build the PDF)
"""
import csv
import json
import urllib.parse
import urllib.request
from bisect import bisect_right
from datetime import datetime, date

# (category, search query, must-include words, must-exclude words)
# words are matched against the scheme name in lowercase with spaces/hyphens removed
FUNDS = [
    ("Index (Nifty 50)", "UTI Nifty 50 Index", ["uti", "nifty50"], ["next", "equal", "value", "alpha", "momentum"]),
    ("Index (Nifty 50)", "ICICI Prudential Nifty 50 Index", ["icici", "nifty50"], ["next", "equal", "value", "alpha", "low", "momentum"]),
    ("Midcap", "Invesco India Mid", ["invesco", "midcap"], ["large", "small"]),
    ("Midcap", "HSBC Midcap", ["hsbc", "midcap"], ["large", "small"]),
    ("Midcap", "WhiteOak Capital Mid Cap", ["whiteoak", "midcap"], ["large", "small"]),
    ("Smallcap", "Bandhan Small Cap", ["bandhan", "smallcap"], []),
    ("Smallcap", "Invesco India Small", ["invesco", "smallcap"], []),
    ("Global index (S&P 500)", "Motilal Oswal S&P 500 Index", ["motilal", "s&p500"], []),
    ("Global index (S&P 500)", "Mirae Asset S&P 500", ["mirae", "s&p500"], []),
    ("Global (Nasdaq 100)", "ICICI Prudential NASDAQ 100 Index", ["icici", "nasdaq100"], []),
    ("Global (Nasdaq 100)", "Motilal Oswal Nasdaq 100 Fund of Fund", ["motilal", "nasdaq100"], ["etf"]),
]

BASE = "https://api.mfapi.in/mf"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(x):
    return x.lower().replace(" ", "").replace("-", "")


def pick_scheme(query, inc, exc):
    """Search by name and pick the Direct + Growth plan matching keywords."""
    results = get_json(BASE + "/search?q=" + urllib.parse.quote(query))
    print("  candidates for '%s':" % query)
    for s in results[:8]:
        print("     ", s["schemeCode"], s["schemeName"])
    for s in results:
        n = norm(s["schemeName"])
        if "direct" not in n or "growth" not in n:
            continue
        if "idcw" in n or "dividend" in n or "bonus" in n:
            continue
        if all(w in n for w in inc) and not any(w in n for w in exc):
            return s
    return None


def load_nav(code):
    data = get_json("%s/%s" % (BASE, code))["data"]
    rows = []
    for d in data:
        try:
            rows.append((datetime.strptime(d["date"], "%d-%m-%Y").date(), float(d["nav"])))
        except Exception:
            pass
    rows.sort()
    return [r[0] for r in rows], [r[1] for r in rows]


def years_back(d, n):
    try:
        return d.replace(year=d.year - n)
    except ValueError:
        return d.replace(year=d.year - n, day=28)


def nav_on_or_before(dates, navs, t):
    i = bisect_right(dates, t) - 1
    return navs[i] if i >= 0 else None


def max_drawdown(navs):
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd * 100


def abs_return(dates, navs, n):
    t = years_back(dates[-1], n)
    if t < dates[0]:
        return None
    old = nav_on_or_before(dates, navs, t)
    return (navs[-1] / old - 1) * 100


def rolling(dates, navs, n):
    out = []
    for i, d in enumerate(dates):
        t = years_back(d, n)
        if t < dates[0]:
            continue
        old = nav_on_or_before(dates, navs, t)
        out.append(((navs[i] / old) ** (1.0 / n) - 1) * 100)
    if not out:
        return None
    return sum(out) / len(out), min(out), max(out)


def fmt(x):
    return "N/A" if x is None else "%.2f" % x


def main():
    rows = []
    for cat, q, inc, exc in FUNDS:
        try:
            s = pick_scheme(q, inc, exc)
            if not s:
                print("NOT FOUND:", q)
                continue
            dates, navs = load_nav(s["schemeCode"])
            ath = max(navs)
            mv, mvd = 0.0, None
            for k in range(1, len(navs)):
                ch = (navs[k] / navs[k - 1] - 1) * 100
                if abs(ch) > abs(mv):
                    mv, mvd = ch, dates[k]
            rec = {
                "category": cat,
                "query": q,
                "scheme_code": s["schemeCode"],
                "scheme_name": s["schemeName"],
                "first_nav_date": dates[0].isoformat(),
                "latest_nav_date": dates[-1].isoformat(),
                "latest_nav": navs[-1],
                "max_drawdown_pct": fmt(max_drawdown(navs)),
                "abs_ret_1y_pct": fmt(abs_return(dates, navs, 1)),
                "abs_ret_3y_pct": fmt(abs_return(dates, navs, 3)),
                "abs_ret_5y_pct": fmt(abs_return(dates, navs, 5)),
                "abs_ret_10y_pct": fmt(abs_return(dates, navs, 10)),
                "below_ATH_pct": fmt((navs[-1] / ath - 1) * 100),
                "biggest_1day_move_pct": fmt(mv),
                "biggest_1day_move_date": str(mvd),
            }
            for n in (1, 5, 10):
                r = rolling(dates, navs, n)
                rec["roll_%dy_avg" % n] = fmt(r[0]) if r else "N/A"
                rec["roll_%dy_min" % n] = fmt(r[1]) if r else "N/A"
                rec["roll_%dy_max" % n] = fmt(r[2]) if r else "N/A"
            rows.append(rec)
            print("OK  :", s["schemeName"], "| code", s["schemeCode"], "| since", dates[0])
        except Exception as e:
            print("FAIL:", q, "->", e)

    if rows:
        with open("fund_metrics.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("\nSaved fund_metrics.csv with %d funds" % len(rows))


if __name__ == "__main__":
    main()
