#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# fix_and_push_intel.command
# Double-click this to: clear git lock → commit intel fix → push → wait for
# Railway to redeploy → run intelligence generation for today's matches.
# ─────────────────────────────────────────────────────────────────────────────

cd "$(dirname "$0")"

echo ""
echo "=== ratethat.tennis — Intel fix + deploy ==="
echo ""

# 1. Remove any stale git lock files
echo "Clearing any git lock files..."
rm -f .git/index.lock .git/HEAD.lock .git/refs/heads/*.lock 2>/dev/null
echo "   Done."

# 2. Commit the intel fix (predictions.py RETURNING fix + any other pending changes)
echo ""
echo "Committing changes..."
git add -A
git commit -m "fix: intel store endpoint + daily intelligence for $(date +%Y-%m-%d)" || {
    echo "   Nothing new to commit (fix may already be committed)."
}

# 3. Push
echo ""
echo "Pushing to origin..."
git push origin deploy-clean || git push --set-upstream origin deploy-clean
echo "   Push complete. Railway will redeploy in ~2 minutes."

# 4. Wait for Railway to redeploy
echo ""
echo "Waiting 90 seconds for Railway to redeploy..."
sleep 90

# 5. Run intelligence generation
echo ""
echo "Running intelligence generation..."
BASE="https://rate-that-tennis-production.up.railway.app"

# Check the API is up
HEALTH=$(curl -s "$BASE/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
echo "   API health: $HEALTH"

if [ "$HEALTH" != "ok" ]; then
    echo "   API not healthy — waiting another 30s..."
    sleep 30
fi

# Activate venv if present
if [ -f "pipeline/venv/bin/activate" ]; then
    source pipeline/venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python3 pipeline/run_intel.py 2>&1 || {
    echo ""
    echo "   run_intel.py not found — running inline generation..."
    python3 << 'PYEOF'
import requests, json, time

BASE = "https://rate-that-tennis-production.up.railway.app"
MODEL = "claude-sonnet-4-6"

def surface_rating(player, surface):
    sr = player.get("surface_ratings", {})
    return sr.get(surface.lower()) or player.get("rtt", 50)

def momentum_phrase(m):
    return {"rising": "in rising form", "falling": "on a falling run"}.get(m, "in stable form")

def fmt_recent(rf, limit=2):
    out = []
    for r in rf[:limit]:
        opp = r.get("opponent_name") or r.get("opp", ""); score=r.get("score",""); oc=r.get("outcome") or r.get("result","")
        if opp and oc:
            s = f"{'beat' if oc=='W' else 'lost to'} {opp}"
            if score: s += f" {score}"
            out.append(s)
    return out

def wl(rf):
    wins = sum(1 for r in rf if (r.get("outcome") or r.get("result","")) == "W")
    return wins, len(rf)

def generate(facts, mid):
    m=facts["match"]; pred=facts["prediction"]
    p1=facts["p1"]; p2=facts["p2"]
    h2h=facts["h2h"]; mkt=facts.get("market",{})
    surf=m.get("surface","Hard"); sl=surf.lower()
    p1n=p1["name"]; p2n=p2["name"]
    p1r=p1.get("rtt",50); p2r=p2.get("rtt",50)
    p1f=p1.get("form",50); p2f=p2.get("form",50)
    p1m=p1.get("momentum","stable"); p2m=p2.get("momentum","stable")
    p1s=surface_rating(p1,surf); p2s=surface_rating(p2,surf)
    p1rc=fmt_recent(p1.get("recent_form",[])); p2rc=fmt_recent(p2.get("recent_form",[]))
    p1wl=wl(p1.get("recent_form",[])); p2wl=wl(p2.get("recent_form",[]))
    prob1=pred.get("prob_first_player",0.5); prob2=pred.get("prob_second_player",0.5)
    conf=pred.get("confidence","medium"); pw=pred.get("predicted_winner","first_player")
    rg=abs(pred.get("rtt_gap",0) or 0); sg=abs(pred.get("surface_gap",0) or 0); fg=abs(pred.get("form_gap",0) or 0)
    fn=p1n if pw=="first_player" else p2n; dn=p2n if pw=="first_player" else p1n
    fp=max(prob1,prob2); fr=p1r if pw=="first_player" else p2r; dr=p2r if pw=="first_player" else p1r
    fs=p1s if pw=="first_player" else p2s; ds=p2s if pw=="first_player" else p1s

    li=[f"{p1n} carries an RTT score of {p1r:.1f} and a {sl} rating of {p1s:.1f}, {momentum_phrase(p1m)}."]
    if p1wl[1]>0:
        li.append(f"They have won {p1wl[0]} of their last {p1wl[1]} matches, with a form index of {p1f:.1f}.")
        if p1rc: li.append(f"Recent results include: {p1rc[0]}.")
    else:
        li.append(f"Their current form index stands at {p1f:.1f}.")
    p1i=" ".join(li)

    l2=[f"{p2n} carries an RTT score of {p2r:.1f} and a {sl} rating of {p2s:.1f}, {momentum_phrase(p2m)}."]
    if p2wl[1]>0:
        l2.append(f"They have won {p2wl[0]} of their last {p2wl[1]} matches, with a form index of {p2f:.1f}.")
        if p2rc: l2.append(f"Recent results include: {p2rc[0]}.")
    else:
        l2.append(f"Their current form index stands at {p2f:.1f}.")
    p2i=" ".join(l2)

    pp=[]
    ht=h2h.get("total",0)
    if ht>0:
        pp.append(f"These two have met {ht} time{'s' if ht!=1 else ''} before, with {p1n} leading {h2h.get('p1_wins',0)}-{h2h.get('p2_wins',0)}.")
    else:
        pp.append(f"This is a first career meeting between {p1n} and {p2n} on {sl}.")
    pp.append(f"The model favours {fn} at {fp*100:.0f}%, driven by an RTT advantage of {rg:.1f} points and a {sl} rating edge of {sg:.1f}.")
    top=sorted([("RTT gap",rg),(f"{sl} rating gap",sg),("form gap",fg)],key=lambda x:x[1],reverse=True)[0]
    pp.append(f"The primary differentiator is {fn}'s {top[0]} of {top[1]:.1f} points.")
    if fg<5 and sg<5:
        pp.append(f"{dn} can win if they keep errors tight and seize break points early.")
    else:
        pp.append(f"{dn} would need to significantly outperform their {sl} rating of {ds:.1f} to upset the model's projection.")
    mp1=mkt.get("p1"); mp2=mkt.get("p2")
    if mp1 and mp2:
        fi=1/mp1 if pw=="first_player" else 1/mp2; edge=fp-fi
        if abs(edge)<0.03:
            pp.append(f"The market's implied probability of {fi*100:.0f}% for {fn} is consistent with the model's {fp*100:.0f}%.")
        elif edge>0.03:
            pp.append(f"The model sees a {edge*100:.0f}-point edge on {fn} over the market's implied {fi*100:.0f}%.")
        else:
            pp.append(f"The market appears to overvalue {fn} at {fi*100:.0f}% implied versus the model's {fp*100:.0f}%.")
    preview=" ".join(pp)

    if p1wl[1]>=5 and p1wl[0]>=p1wl[1]-1:
        dyk=f"{p1n} has won {p1wl[0]} of their last {p1wl[1]} matches."
    elif p2wl[1]>=5 and p2wl[0]>=p2wl[1]-1:
        dyk=f"{p2n} has won {p2wl[0]} of their last {p2wl[1]} matches."
    elif ht>2 and h2h.get("p1_wins",0)>h2h.get("p2_wins",0)+1:
        dyk=f"{p1n} leads the all-time head-to-head {h2h['p1_wins']}-{h2h['p2_wins']}."
    elif ht>2 and h2h.get("p2_wins",0)>h2h.get("p1_wins",0)+1:
        dyk=f"{p2n} leads the all-time head-to-head {h2h['p2_wins']}-{h2h['p1_wins']}."
    elif sg>25:
        dyk=f"The {sl} rating gap between these players is {sg:.0f} points — one of the larger surface mismatches on today's card."
    elif rg>20:
        dyk=f"{fn}'s RTT of {fr:.1f} is {rg:.0f} points ahead of {dn}'s {dr:.1f}."
    elif p1m=="rising" and p2m=="falling":
        dyk=f"{p1n} is rated as rising in momentum while {p2n} is on a falling trend."
    elif p2m=="rising" and p1m=="falling":
        dyk=f"{p2n} is rated as rising in momentum while {p1n} is on a falling trend."
    else:
        dyk=f"The RTT gap of {rg:.1f} gives this match a {conf}-confidence rating from the model."

    top2=sorted([("RTT",rg),(f"{sl} rating",sg),("form",fg)],key=lambda x:x[1],reverse=True)[0]
    cl=f"The model has {conf} confidence here, anchored by a {top2[0]} gap of {top2[1]:.1f} points."

    return {"p1_intel":p1i,"p2_intel":p2i,"match_preview":preview,"did_you_know":dyk,"confidence_line":cl,"model":MODEL}

# Fetch queue
r = requests.get(f"{BASE}/api/v1/admin/intel/queue?days_ahead=2", timeout=15)
queue = r.json().get("queue", [])
count = r.json().get("count", 0)
print(f"Queue: {count} matches need intelligence")

if count == 0:
    print("Nothing to do.")
    exit(0)

ok=0; fail=[]
for item in queue:
    mid = item["match_id"]
    try:
        r=requests.get(f"{BASE}/api/v1/matches/{mid}/intelligence",timeout=12)
        if r.status_code!=200: fail.append((mid,f"facts {r.status_code}")); print(f"FAIL {mid}: facts {r.status_code}"); continue
        data=r.json(); facts=data.get("facts",{})
        if not facts or not facts.get("prediction"): fail.append((mid,"no pred")); print(f"SKIP {mid}: no pred"); continue
        intel=generate(facts,mid)
        sr=requests.post(f"{BASE}/api/v1/admin/intel/store/{mid}",json=intel,timeout=12)
        if sr.status_code==200 and sr.json().get("ok"):
            ok+=1; print(f"OK  {mid}: {facts['p1']['name']} vs {facts['p2']['name']}")
        else:
            fail.append((mid,f"store {sr.status_code}")); print(f"FAIL {mid}: store {sr.status_code} {sr.text[:60]}")
    except Exception as e:
        fail.append((mid,str(e)[:80])); print(f"ERR  {mid}: {e}")
    time.sleep(0.05)

print(f"\n=== DONE: {ok} succeeded, {len(fail)} failed ===")
PYEOF
}

echo ""
echo "=== Intelligence generation complete ==="
echo ""
read -p "Press Enter to close..."
