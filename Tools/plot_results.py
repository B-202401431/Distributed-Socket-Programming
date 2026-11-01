#!/usr/bin/env python3
"""Generate figures from successful, SHA-256-verified experimental runs."""
import argparse,csv,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def generate(summary,label):
    summary=Path(summary)
    with summary.open() as f:all_rows=list(csv.DictReader(f))
    rows=[r for r in all_rows if r.get('status')=='SUCCESS' and r.get('sha256_verified')=='1']
    out=summary.parent
    plt.rcParams.update({'font.size':9,'figure.dpi':140})
    def chart(name,xlabel,ylabel,series):
        fig,ax=plt.subplots(figsize=(6.6,3.6))
        used=False
        for name_,points in series:
            if not points:continue
            xs=sorted(points);means=[statistics.mean(points[x]) for x in xs]
            errors=[statistics.stdev(points[x]) if len(points[x])>1 else 0 for x in xs]
            ax.errorbar(xs,means,yerr=errors,marker='o',capsize=3,label=name_);used=True
        if not used:plt.close(fig);return
        ax.set(xlabel=xlabel,ylabel=ylabel,title=label);ax.set_ylim(bottom=0)
        ax.grid(alpha=.25);ax.legend(fontsize=8);fig.tight_layout()
        for suffix in ['png','pdf']:fig.savefig(out/(name+'.'+suffix))
        plt.close(fig)
    def grouped(case,mode,x,y):
        points={}
        for r in rows:
            if r['case']==case and r['mode']==mode:
                points.setdefault(float(r[x]),[]).append(float(r[y]))
        return points
    chart('Part1_throughput','Concurrent client processes','Useful goodput (MiB/s)',
          [(m,grouped('Part1',m,'clients','goodput_MiB_s')) for m in ['single','multi']])
    for metric,suffix,ylabel in [('goodput_MiB_s','throughput','Useful goodput (MiB/s)'),
        ('redundancy_percent','overhead','Redundant payload / useful payload (%)')]:
        series=[]
        for case,name in [('Part2_Case1','Restart'),('Part2_Case2','Resume'),('Part2_Case2_Enhanced','Parallel resume')]:
            points=grouped(case,'multi','probability',metric);series.append((name,points))
            chart(case+'_'+suffix,'Failure probability per payload block',ylabel,[(name,points)])
        chart('Part2_comparison_'+suffix,'Failure probability per payload block',ylabel,series)
    failed=[r for r in all_rows if r not in rows]
    (out/'plot_notes.txt').write_text(f'{len(rows)} successful verified runs plotted; {len(failed)} failed/unverified runs retained in summary.csv. Error bars: sample standard deviation.\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('summary',type=Path)
    p.add_argument('--label',default='Local synthetic tests - one computer')
    a=p.parse_args();generate(a.summary,a.label)
