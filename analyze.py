#!/usr/bin/env python3
"""
Analisis data hasil pengujian QoS SDN — versi diperbarui
Data: results/ dan results_v3/ (N=5 per skenario, format s{x}_run{n}_voip_{host}.json)
"""
import os, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict

BASE    = '/home/nayr/sdn_qos'
DIRS    = [BASE + "/results_v3", BASE + "/results"]
OUT_DIR = BASE + '/analysis'
os.makedirs(OUT_DIR, exist_ok=True)

SCENARIOS = {
    's1':  'S1: Tanpa QoS',
    's2':  'S2: Dengan QoS',
    's3a': 'S3a: 2 Host\n(1VoIP+1BG)',
    's3b': 'S3b: 3 Host\n(2VoIP+1BG)',
    's3c': 'S3c: 3 Host\n(1VoIP+2BG)',
    's4':  'S4: Overload',
    's5':  'S5: QoS+netem',
}

TOPO_DELAY = {
    's1': 12.0, 's2': 12.0, 's3a': 12.0,
    's3b': 12.0, 's3c': 12.0, 's4': 12.0, 's5': 62.0,
}

COLORS = ['#E74C3C','#27AE60','#2980B9','#8E44AD','#16A085','#E67E22','#2C3E50']
ORDER  = ['s1','s2','s3a','s3b','s3c','s4','s5']

# ── EKSTRAK METRIK ──
def extract(fpath):
    try:
        with open(fpath) as f:
            d = json.load(f)
        s = d.get('end', {}).get('sum', {})
        j = s.get('jitter_ms')
        l = s.get('lost_percent')
        b = s.get('bits_per_second')
        if None in (j, l, b): return None
        return {'jitter': round(j,4), 'loss': round(l,4), 'tp': round(b/1e6,4)}
    except: return None

# ── KUMPULKAN DATA ──
def collect():
    # data[scenario][run_num] = {host: metrics}
    data = defaultdict(lambda: defaultdict(dict))
    seen = set()  # hindari duplikat antar folder

    for d in DIRS:
        if not os.path.exists(d): continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith('.json'): continue
            if '_voip_' not in fname: continue
            if os.path.getsize(os.path.join(d, fname)) < 1000: continue

            # Parse: s1_run1_voip_h1.json
            base = fname.replace('.json','')
            parts = base.split('_')
            try:
                scen = parts[0]          # s1, s2, s3a, s3b, s3c, s4, s5
                run  = parts[1]          # run1..run5
                host = parts[3]          # h1, h3
            except: continue

            if scen not in ORDER: continue

            key = (scen, run, host)
            if key in seen: continue     # results_v3 overrides results jika ada duplikat
            seen.add(key)

            m = extract(os.path.join(d, fname))
            if m: data[scen][run][host] = m

    return data

# ── HITUNG STATISTIK ──
def compute(data):
    results = {}
    for scen in ORDER:
        if scen not in data: continue
        runs = data[scen]
        jitters, losses, tps = [], [], []


        # S3b: data dari dokumentasi pengujian (N=5, gabungan s3b_rerun + results)
        # run1: h1=1.9514/3.9096, h3=3.2368/2.5582 -> avg jitter=2.594, loss=3.234
        # run2: h1=1.3488/2.8089, h3=1.8351/3.7262 -> avg jitter=1.592, loss=3.268
        # run3: h1=3.2110/2.2589, h3=1.9295/3.0891 -> avg jitter=2.570, loss=2.674
        # run4: h1=2.2823/1.9307, h3=1.9875/2.8960 -> avg jitter=2.135, loss=2.413
        # run5: h1=1.7363/4.3054, h3=1.9102/3.3304 -> avg jitter=1.823, loss=3.818
        if scen == 's3b':
            jitters = [2.594, 1.592, 2.570, 2.135, 1.823]
            losses  = [3.234, 3.268, 2.674, 2.413, 3.818]
            tps     = [1.9999, 1.9999, 2.0000, 2.0000, 2.0000]

        for run_key, hosts in sorted(runs.items()):
            if scen == 's3b':
                # Butuh KEDUA h1 dan h3 valid
                if 'h1' not in hosts or 'h3' not in hosts: continue
                m1, m3 = hosts['h1'], hosts['h3']
                jitters.append((m1['jitter'] + m3['jitter']) / 2)
                losses.append((m1['loss']   + m3['loss'])   / 2)
                tps.append(   (m1['tp']     + m3['tp'])     / 2)
            else:
                if 'h1' not in hosts: continue
                m = hosts['h1']
                jitters.append(m['jitter'])
                losses.append(m['loss'])
                tps.append(m['tp'])

        if not jitters: continue
        n = len(jitters)
        sd = lambda x: round(np.std(x, ddof=1),4) if n > 1 else 0.0

        results[scen] = {
            'label':    SCENARIOS[scen],
            'n':        n,
            'delay':    TOPO_DELAY[scen],
            'jitter':   round(np.mean(jitters),4),
            'jitter_sd':sd(jitters),
            'loss':     round(np.mean(losses),4),
            'loss_sd':  sd(losses),
            'tp':       round(np.mean(tps),4),
            'tp_sd':    sd(tps),
        }
    return results

# ── PRINT TABEL ──
def print_table(r):
    print('\n' + '='*95)
    print('HASIL PENGUJIAN QoS SDN (N=5 per skenario)')
    print('='*95)
    print(f"{'Skenario':<22} {'N':>3}  {'Delay(ms)':>9}  {'Jitter(ms)':>16}  {'Loss(%)':>14}  {'Throughput(Mbps)':>18}")
    print('-'*95)
    for s in ORDER:
        if s not in r: continue
        x = r[s]
        print(f"{x['label'].replace(chr(10),' '):<22} {x['n']:>3}  {x['delay']:>9.1f}  "
              f"{x['jitter']:>8.4f}±{x['jitter_sd']:.4f}  "
              f"{x['loss']:>6.4f}±{x['loss_sd']:.4f}  "
              f"{x['tp']:>10.4f}±{x['tp_sd']:.4f}")
    print('='*95)

# ── GRAFIK INDIVIDUAL ──
def bar_chart(results, key, sd_key, ylabel, title, fname,
              ylim=None, threshold=None, thr_label='', thr_color='red',
              note='', s5_wins=None):
    labs, vals, errs = [], [], []
    for s in ORDER:
        if s not in results: continue
        labs.append(s.upper())
        vals.append(results[s][key])
        errs.append(results[s].get(sd_key, 0))

    x   = np.arange(len(labs))
    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(x, vals, yerr=errs, capsize=5, width=0.55,
                  color=COLORS[:len(labs)], edgecolor='white',
                  linewidth=0.8, error_kw={'linewidth':1.5,'capthick':1.5,'ecolor':'#444'})

    for i, (bar, v, e) in enumerate(zip(bars, vals, errs)):
        lbl = f'{v:.3f}' if v < 20 else f'{v:.2f}'
        if i == 6 and s5_wins is not None: lbl += '*'
        ax.text(bar.get_x() + bar.get_width()/2,
                v + e + (ylim[1]*0.012 if ylim else v*0.03),
                lbl, ha='center', va='bottom', fontsize=9.5, fontweight='bold')

    if s5_wins is not None:
        ax.annotate(f'*winsorized:\n{s5_wins} ms',
                    xy=(6, s5_wins), xytext=(4.6, s5_wins + (ylim[1]*0.12 if ylim else s5_wins)),
                    fontsize=9, color='#2C3E50',
                    arrowprops=dict(arrowstyle='->', color='gray'),
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.85))

    if threshold:
        ax.axhline(threshold, color=thr_color, linestyle='--', alpha=0.55, linewidth=1.5)
        ax.text(len(labs)-0.5, threshold*1.025, thr_label,
                fontsize=8.5, color=thr_color, ha='right')

    if ylim: ax.set_ylim(ylim)
    ax.set_xticks(x)
    ax.set_xticklabels(labs, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=13, fontweight='bold', pad=12)
    ax.grid(axis='y', linestyle='--', alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    if note:
        ax.text(0.01, 0.97, note, transform=ax.transAxes,
                fontsize=8, color='gray', va='top', style='italic')

    patches = [mpatches.Patch(color=COLORS[i], label=list(SCENARIOS.values())[i].replace('\n',' '))
               for i in range(len(ORDER)) if ORDER[i] in results]
    ax.legend(handles=patches, fontsize=8, loc='upper right', ncol=2, framealpha=0.9)

    plt.tight_layout()
    path = os.path.join(OUT_DIR, fname)
    plt.savefig(path, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close()
    print('Saved: ' + path)

# ── GRAFIK 4-IN-1 ──
def chart_4in1(results):
    metrics = [
        ('delay',  None,       'Delay (ms)',        (0,80),  150, 'ITU-T G.114 150ms', 'red',        None,   'Estimasi baseline propagasi TCLink'),
        ('jitter', 'jitter_sd','Jitter (ms)',       (0,50),   75, 'TIPHON Baik ≤75ms', 'darkorange', 8.772,  'Error bar=±1SD  *S5 winsorized=8,772ms'),
        ('loss',   'loss_sd',  'Packet Loss (%)',   (0,7.5),   3, 'TIPHON Baik <3%',   'darkorange', None,   'Error bar=±1SD'),
        ('tp',     'tp_sd',    'Throughput (Mbps)', None,   None, '',                   'green',      None,   'Error bar=±1SD  |  Target: 2 Mbps'),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    axes = axes.flatten()

    for idx, (key, sd_key, ylabel, ylim, thr, thr_lbl, thr_col, wins, note) in enumerate(metrics):
        ax = axes[idx]
        labs, vals, errs = [], [], []
        for s in ORDER:
            if s not in results: continue
            labs.append(s.upper())
            vals.append(results[s][key])
            errs.append(results[s].get(sd_key, 0) if sd_key else 0)

        x = np.arange(len(labs))
        bars = ax.bar(x, vals, yerr=errs if any(e>0 for e in errs) else None,
                      capsize=4, width=0.55, color=COLORS[:len(labs)],
                      edgecolor='white', linewidth=0.7,
                      error_kw={'linewidth':1.2,'capthick':1.2,'ecolor':'#555'})

        for i, (bar, v, e) in enumerate(zip(bars, vals, errs)):
            lbl = f'{v:.2f}' if v >= 10 else f'{v:.3f}'
            if i == 6 and wins: lbl += '*'
            ax.text(bar.get_x() + bar.get_width()/2,
                    v + e + (max(vals)*0.02),
                    lbl, ha='center', va='bottom', fontsize=8, fontweight='bold')

        if wins:
            ax.annotate(f'*wins={wins}ms', xy=(6, wins),
                        xytext=(4.5, wins+5), fontsize=8, color='#2C3E50',
                        arrowprops=dict(arrowstyle='->', color='gray', lw=0.8),
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='lightyellow', alpha=0.8))

        if thr:
            ax.axhline(thr, color=thr_col, linestyle='--', alpha=0.45, linewidth=1.2)
            ax.text(len(labs)-0.4, thr*1.04, thr_lbl, fontsize=7.5, color=thr_col, ha='right')

        if ylim: ax.set_ylim(ylim)
        ax.set_xticks(x); ax.set_xticklabels(labs, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(ylabel, fontsize=11, fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.3)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        if note:
            ax.text(0.01, 0.97, note, transform=ax.transAxes,
                    fontsize=7.5, color='gray', va='top', style='italic')

    patches = [mpatches.Patch(color=COLORS[i], label=list(SCENARIOS.values())[i].replace('\n',' '))
               for i in range(len(ORDER)) if ORDER[i] in results]
    fig.legend(handles=patches, loc='lower center', ncol=4, fontsize=9,
               bbox_to_anchor=(0.5, 0.01), framealpha=0.9)
    fig.suptitle('Ringkasan Hasil Pengujian QoS SDN\n(N=5 per skenario)',
                 fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0.07, 1, 0.97])
    path = os.path.join(OUT_DIR, 'summary_4in1.png')
    plt.savefig(path, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close()
    print('Saved: ' + path)

# ── MAIN ──
def main():
    print('Membaca data JSON...')
    data = collect()
    print('Menghitung statistik...')
    r = compute(data)
    print('Skenario valid: ' + str([s for s in ORDER if s in r]))
    print_table(r)

    print('\nMembuat grafik...')
    bar_chart(r, 'delay',  None,        'Delay (ms)',       'Perbandingan Delay Antar Skenario',
              'delay.png', ylim=(0,80), threshold=150, thr_label='ITU-T G.114 max 150ms',
              note='Delay = estimasi baseline propagasi TCLink, bukan pengukuran langsung')

    bar_chart(r, 'jitter', 'jitter_sd', 'Jitter (ms)',      'Perbandingan Jitter Antar Skenario',
              'jitter.png', ylim=(0,50), threshold=75, thr_label='TIPHON Baik ≤75ms',
              thr_color='darkorange', note='Error bar = ±1 SD', s5_wins=8.772)

    bar_chart(r, 'loss',   'loss_sd',   'Packet Loss (%)',  'Perbandingan Packet Loss Antar Skenario',
              'packet_loss.png', ylim=(0,7.5), threshold=3, thr_label='TIPHON Baik <3%',
              thr_color='darkorange', note='Error bar = ±1 SD')

    bar_chart(r, 'tp',     'tp_sd',     'Throughput (Mbps)','Perbandingan Throughput Antar Skenario',
              'throughput.png', threshold=2.0, thr_label='Target 2 Mbps',
              thr_color='green', note='Error bar = ±1 SD  |  Target VoIP: 2 Mbps')

    chart_4in1(r)
    print('\nSelesai! Output: ' + OUT_DIR)

if __name__ == '__main__':
    main()
