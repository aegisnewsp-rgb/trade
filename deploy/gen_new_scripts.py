import glob, re, sys

already_in_readme = {
    'live_AETHERIND_NS.py', 'live_AETHERIND.py', 'live_ADANIENT.py',
    'live_TECHM.py', 'live_TATAELXSI.py', 'live_SUNPHARMA.py', 'live_SIEMENS.py',
    'live_SCHAEFFLER.py', 'live_SAGILITY.py', 'live_OLECTRA.py', 'live_MM_NS.py',
    'live_MAPMYINDIA.py', 'live_LTIM.py', 'live_LTES.py', 'live_LT.py',
    'live_ICICIBANK.py', 'live_HINDUNILVR.py', 'live_HCLTECH_NS.py', 'live_CENTUM.py',
    'live_BAJFINANCE.py', 'live_AXISBANK.py', 'live_ITC.py', 'live_IPCALAB.py',
    'live_ADANIPOWER.py', 'live_ADANIGREEN.py', 'live_ADANIPORTS.py', 'live_ULTRACEMCO.py',
    'live_TCS.py', 'live_SBIN.py', 'live_RELIANCE.py', 'live_INDUSIND.py', 'live_DRREDDY.py',
    'live_BANKBARODA.py', 'live_APOLLOTYRE.py', 'live_GODREJPROP_NS.py', 'live_UCOBANK.py',
    'live_COLPAL.py', 'live_HAVELLS.py', 'live_IOB.py', 'live_EICHERMOT.py',
    'live_TITAN.py', 'live_HDFCBANK.py', 'live_IGL.py', 'live_SRF_NS.py', 'live_CIPLA.py',
    'live_BANKINDIA.py', 'live_COALINDIA_NS.py', 'live_BOSCHLTD.py', 'live_NESTLEIND_NS.py',
    'live_IDEA.py', 'live_SBILIFE_NS.py', 'live_HINDPETRO_NS.py', 'live_MARUTI_NS.py',
    'live_ACC.py', 'live_POWERGRID_NS.py', 'live_INDHOTEL.py', 'live_CENTRALBK.py',
    'live_ASIANPAINT.py', 'live_TATASTEEL.py', 'live_SHREECEM_NS.py', 'live_ABB.py',
    'live_ALKEM.py', 'live_BPCL.py', 'live_CHOLAFIN.py', 'live_GRASIM.py', 'live_DABUR.py',
    'live_HEROMOTOCO.py', 'live_WIPRO.py'
}

new_scripts = []
for f in sorted(glob.glob('live_*.py')):
    name = f.split('/')[-1]
    if name not in already_in_readme:
        with open(f) as fp:
            content = fp.read(3000)
        sym_match = re.search(r'SYMBOL\s*=\s*["\x27]([^"\x27]+)["\x27]', content)
        strat_match = re.search(r'STRATEGY\s*=\s*["\x27]([^"\x27]+)["\x27]', content)
        sym = sym_match.group(1) if sym_match else 'N/A'
        strat = strat_match.group(1) if strat_match else 'N/A'
        new_scripts.append((name, sym, strat))

print(f'New scripts to add: {len(new_scripts)}')
lines = []
for s in new_scripts:
    lines.append(f'| `{s[0]}` | {s[1]} | {s[2]} | N/A |')

output = '\n'.join(lines)
with open('/tmp/new_scripts_table.md', 'w') as f:
    f.write(output)
print(output)
