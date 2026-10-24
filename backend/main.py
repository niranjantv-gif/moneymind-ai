"""MoneyMind AI - transparent cash-flow engine + explanations.
Run:  uvicorn main:app --reload --port 8000
Optional: set ANTHROPIC_API_KEY to get a Claude-written explanation on top of the rule-based one."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MoneyMind AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---- Demo profile (swap for a DB / user input later) ----
PROFILE = {
    "balance": 9000,           # INR today
    "daily": 200,              # average daily living spend
    "buffer": 1000,            # minimum safe balance
    "events": [                # signed amounts: + income, - commitment
        {"day": 3,  "name": "Pocket money",   "amount": 10000},
        {"day": 5,  "name": "Rent",           "amount": -8000},
        {"day": 9,  "name": "Mobile recharge","amount": -399},
        {"day": 12, "name": "Subscriptions",  "amount": -199},
        {"day": 15, "name": "Course fee",     "amount": -3500},
        {"day": 20, "name": "Freelance pay",  "amount": 4000},
    ],
}
inr = lambda x: f"₹{x:,.0f}"

# ---- Calculation engine ----
def forecast(extra=None, cut=0.0, days=30):
    bal, pts = PROFILE["balance"], []
    for d in range(1, days + 1):
        bal -= PROFILE["daily"] * (1 - cut)
        bal += sum(e["amount"] for e in PROFILE["events"] if e["day"] == d)
        bal -= sum(x["amount"] for x in (extra or []) if x["day"] == d)
        pts.append({"day": d, "balance": round(bal)})
    return pts

def summarize(pts):
    low = min(pts, key=lambda p: p["balance"])
    neg = next((p["day"] for p in pts if p["balance"] < 0), None)
    status = "danger" if low["balance"] < 0 else "tight" if low["balance"] < PROFILE["buffer"] else "safe"
    return {"min": low["balance"], "min_day": low["day"], "end": pts[-1]["balance"],
            "first_negative": neg, "status": status}

def scenarios(amount, day):
    nxt = max((e["day"] for e in PROFILE["events"] if e["amount"] > 0 and e["day"] > day), default=30)  # last payday ahead
    defs = [
        ("skip",  "Don't buy",                    [], 0),
        ("now",   f"Buy on day {day}",            [{"day": day, "amount": amount}], 0),
        ("wait",  f"Wait until day {nxt}",        [{"day": nxt, "amount": amount}], 0),
        ("split", "Pay in 2 halves",              [{"day": day, "amount": amount / 2}, {"day": min(day + 14, 30), "amount": amount / 2}], 0),
        ("trim",  "Buy now + cut daily spend 20%",[{"day": day, "amount": amount}], 0.2),
    ]
    out = []
    for id_, label, extra, cut in defs:
        pts = forecast(extra, cut)
        out.append({"id": id_, "label": label, "points": pts, "summary": summarize(pts)})
    return out

def explain(item, amount, day):
    sc = scenarios(amount, day)
    now = sc[1]["summary"]
    reasons, alts = [], []
    if now["status"] == "safe":
        headline = f"Safe to buy: your lowest balance stays at {inr(now['min'])}."
    else:
        headline = ("Warning: this would take you below zero." if now["status"] == "danger"
                    else "Caution: this leaves you under your safety buffer.")
        reasons.append(f"Buying {item} for {inr(amount)} on day {day} pushes your lowest balance to {inr(now['min'])} on day {now['min_day']}.")
        due = [e for e in PROFILE["events"] if e["amount"] < 0 and day <= e["day"] <= now["min_day"]]
        if due:
            reasons.append("Commitments landing before that low point: " + ", ".join(f"{e['name']} {inr(-e['amount'])} (day {e['day']})" for e in due) + ".")
        if now["first_negative"]:
            reasons.append(f"You'd run out of money on day {now['first_negative']}.")
        for s in sc[2:]:
            sm = s["summary"]
            if sm["status"] != "danger":
                alts.append(f"{s['label']}: lowest balance {inr(sm['min'])} ({sm['status']}).")
    text = headline + " " + " ".join(reasons)
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            msg = anthropic.Anthropic().messages.create(
                model="claude-sonnet-4-6", max_tokens=300,
                messages=[{"role": "user", "content":
                    f"You are a friendly money coach for students. In 3 short sentences, explain this using ONLY these facts, no new numbers: {text} Alternatives: {alts}"}])
            text = msg.content[0].text
        except Exception:
            pass
    return {"headline": headline, "reasons": reasons, "alternatives": alts, "text": text, "status": now["status"]}

# ---- API ----
class Purchase(BaseModel):
    item: str = "Purchase"
    amount: float
    day: int = 1

@app.get("/api/dashboard")
def dashboard():
    pts = forecast()
    ev = PROFILE["events"]
    return {"balance": PROFILE["balance"], "daily": PROFILE["daily"], "buffer": PROFILE["buffer"],
            "events": ev, "commitments": -sum(e["amount"] for e in ev if e["amount"] < 0),
            "income": sum(e["amount"] for e in ev if e["amount"] > 0),
            "points": pts, "summary": summarize(pts)}

@app.post("/api/simulate")
def simulate(p: Purchase):
    return {"scenarios": scenarios(p.amount, p.day)}

@app.post("/api/explain")
def explain_ep(p: Purchase):
    return explain(p.item, p.amount, p.day)
