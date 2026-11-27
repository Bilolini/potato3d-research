"""Presentation only: saved synthetic meshes -> offline viewer and error-field figure."""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from plotly.offline import get_plotlyjs
import trimesh

from potato3d.geometry import sample_surface, subset
from potato3d.io import sha256, write_json
from potato3d.metrics import surface_distances


ROOT = Path(__file__).resolve().parents[2]
COURSE = ROOT/"course"
CASES = [
    ("spatial_confidence_confirmation_v1", "spatial_confirmation_family_00_warp_0", "clean", "Reliable clean surface",
     "Local repair keeps the clean observations. This smooth synthetic case does not test preservation of a genuine protrusion.",
     ["symmetry", "symmetry_robust95", "symmetry_spatial"]),
    ("spatial_confidence_confirmation_v1", "spatial_confirmation_family_00_warp_0", "outliers_2percent", "Isolated spikes: local repair helps",
     "Injected positive spikes corrupt the mirror height. Local support selects them for repair on this controlled case.",
     ["symmetry", "symmetry_robust95", "symmetry_spatial"]),
    ("spatial_confidence_confirmation_v1", "spatial_confirmation_family_00_warp_0", "correlated_outlier_patch", "Coherent patch: local support fails",
     "Nearby erroneous points support one another. Local geometric agreement is not proof that the depth is correct.",
     ["symmetry", "symmetry_robust95", "symmetry_spatial"]),
    ("multiscale_confidence_confirmation_v1", "multiscale_confirmation_family_00_smooth_warp_0", "correlated_outlier_patch", "Broader support repairs the patch",
     "The boundary-gated annular rule improves this patch case. Its full confirmation hypothesis still failed two of seven criteria.",
     ["symmetry_robust95", "symmetry_spatial", "symmetry_multiscale"]),
    ("multiscale_confidence_confirmation_v1", "multiscale_confirmation_family_00_narrow_warp_0", "genuine_narrow_protrusion", "True narrow feature: repair can damage it",
     "This protrusion belongs to the clean shape. Removing it is an error, even when a global hidden-surface mean looks favorable.",
     ["symmetry", "symmetry_spatial", "symmetry_multiscale"]),
    ("spatial_confidence_confirmation_v1", "spatial_confirmation_family_00_warp_1.8", "clean", "Hidden twin: same input, different underside",
     "Compare with the first clean case. The observations and predictions match, but this reference has a different hidden underside.",
     ["symmetry", "symmetry_robust95", "symmetry_spatial"]),
]
NAMES = {"symmetry": "Mirror maximum", "symmetry_robust95": "Fixed q95",
         "symmetry_spatial": "Local repair", "symmetry_multiscale": "Boundary-gated multiscale"}


def coordinates(points):
    return np.round(points, 4).T.tolist()


def build():
    for folder in ["showcase", "figures", "evidence"]:
        (COURSE/folder).mkdir(parents=True, exist_ok=True)
    provenance = {"role": "post-hoc presentation from saved geometry; no prediction fitting or aggregate rescoring",
                  "visualization_seed": 5271313, "samples_per_surface": 1800, "color_range_mm": [0, 8],
                  "display_distance": "exact one-way prediction-sample to reference-triangle distance; color saturates above 8 mm",
                  "case_selection": "fixed family 0; not performance-selected; profiles and conditions named explicitly", "cases": []}
    records = []
    for run_name, pid, condition, title, description, methods in CASES:
        run = ROOT/"outputs"/run_name
        folder = run/pid/condition
        reference = trimesh.load(folder/"reference.ply", force="mesh", process=False)
        partial = np.asarray(trimesh.load(folder/"partial.ply", process=False).vertices)
        ref_points, _ = sample_surface(reference, 1800, 5271313)
        rows = json.loads((run/"results.json").read_text())
        case = {"title": title, "description": description, "input": coordinates(subset(partial, 2500, 5271313)),
                "reference": coordinates(ref_points), "methods": {}}
        files = [run/"results.json", folder/"partial.ply", folder/"reference.ply"]
        for method in methods:
            mesh = trimesh.load(folder/(method+".ply"), force="mesh", process=False)
            points, _ = sample_surface(mesh, 1800, 5271313)
            distances = surface_distances(points, reference)
            row = next(r for r in rows if r["object_id"] == pid and r["condition"] == condition and r["method"] == method)
            if row["status"] != "ok":
                raise ValueError("Cannot show a failed prediction as successful")
            case["methods"][method] = {"name": NAMES[method], "points": coordinates(points),
                "distance": np.round(distances, 4).tolist(),
                "scores": {k: row.get(k) for k in ["chamfer_l1_mm", "hidden_chamfer_l1_mm", "fscore_5mm", "feature_observed_to_surface_mean_mm"]}}
            files.extend([folder/(method+".ply"), folder/(method+"_parameters.json")])
        records.append(case)
        provenance["cases"].append({"run": run_name, "object_id": pid, "condition": condition,
                                     "methods": methods, "files": {str(p.relative_to(ROOT)): sha256(p) for p in files}})
    write_json(COURSE/"evidence/showcase_provenance.json", provenance)
    # This JSON is synthetic display data, not a new benchmark results table.
    data = json.dumps(records, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = HTML.replace("__PLOTLY__", get_plotlyjs()).replace("__DATA__", data)
    (COURSE/"showcase/index.html").write_text(html)
    # Three cases expose both success and failure under one fixed error scale.
    selected = [(1, "symmetry_spatial"), (2, "symmetry_spatial"), (4, "symmetry_multiscale")]
    fig = plt.figure(figsize=(8.2, 3.5), layout="constrained")
    for index, (case_index, method) in enumerate(selected):
        case = records[case_index]; current = case["methods"][method]
        ax = fig.add_subplot(1, 3, index+1, projection="3d")
        points = np.asarray(current["points"]).T
        cloud = ax.scatter(*points.T, c=current["distance"], s=3, cmap="magma", norm=Normalize(0, 8), rasterized=True)
        ax.set_title(["Spikes / local", "Patch / local", "True feature / multiscale"][index], fontsize=10)
        ax.set(xlabel="x", ylabel="y", zlabel="z")
        ax.set_box_aspect(np.maximum(np.ptp(points, axis=0), 1)); ax.view_init(elev=22, azim=-65)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    fig.colorbar(cloud, ax=fig.axes, shrink=.65, pad=.025, label="Distance (mm; saturated at 8)")
    fig.suptitle("Saved synthetic family 0: repair success and two failure modes", fontsize=11)
    fig.savefig(COURSE/"figures/error_fields.png", dpi=180); plt.close(fig)
    figure_sources = {"error_fields.png": {"source": "showcase_provenance.json", "sha256": sha256(COURSE/"figures/error_fields.png")}}
    for name, source in result_figures().items():
        figure_sources[name] = {"source": source, "source_sha256": sha256(ROOT/source), "sha256": sha256(COURSE/"figures"/name),
                                "operation": "publication-sized redraw from saved values; no fitting or metric recomputation"}
    write_json(COURSE/"evidence/figure_provenance.json", figure_sources)
    print("Built six offline synthetic cases and four report figures from unchanged artifacts")


def result_figures():
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9})
    sources = {"spatial_confirmation.png": "outputs/spatial_confidence_confirmation_v1_analysis/analysis.json",
               "multiscale_tradeoffs.png": "docs/multiscale_confidence_results.json",
               "bonn_objects.png": "outputs/bonn_holdout_v1/results.json"}
    spatial = json.loads((ROOT/sources["spatial_confirmation.png"]).read_text())
    conditions = ["clean", "depth_jitter_2mm", "outliers_2percent", "depth_gap", "belt_plus3mm", "belt_minus3mm", "correlated_outlier_patch"]
    labels = ["Clean", "2 mm jitter", "Isolated spikes", "Missing depth", "Belt +3 mm", "Belt -3 mm", "Coherent patch"]
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.4), sharey=True, layout="constrained")
    for ax, metric, unit in zip(axes, ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml"], ["mm", "mL"]):
        rows = {r["condition"]: r for r in spatial["paired_comparisons"] if r["candidate"] == "symmetry_spatial" and r["baseline"] == "symmetry_robust95" and r["metric"] == metric and r["profile"] == "combined"}
        values = np.array([rows[c]["mean"] for c in conditions]); ci = np.array([rows[c]["ci95"] for c in conditions])
        ax.errorbar(values, np.arange(7), xerr=np.maximum(np.array([values-ci[:, 0], ci[:, 1]-values]), 0), fmt="o", color="#147879", capsize=3)
        ax.axvline(0, color="#778890", ls="--", lw=1)
        ax.set(xlabel=f"Local - q95 ({unit})", yticks=np.arange(7), yticklabels=labels)
        ax.set_title("Hidden Chamfer" if unit == "mm" else "Analytic volume MAE")
        ax.grid(axis="x", alpha=.2); ax.spines[["top", "right"]].set_visible(False)
    axes[0].invert_yaxis()
    fig.savefig(COURSE/"figures/spatial_confirmation.png", dpi=200); plt.close(fig)
    multi = json.loads((ROOT/sources["multiscale_tradeoffs.png"]).read_text())
    methods = ["symmetry", "symmetry_robust95", "symmetry_spatial", "symmetry_annular", "symmetry_multiscale"]
    labels = ["Mirror", "q95", "Local", "Annular", "Gated"]
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.6), layout="constrained")
    for index, (method, label) in enumerate(zip(methods, labels)):
        for ax, conditions, metric in [(axes[0], ["outliers_2percent", "correlated_outlier_patch"], "hidden_chamfer_l1_mm"),
                                       (axes[1], ["genuine_wide_protrusion", "genuine_narrow_protrusion"], "feature_observed_to_surface_mean_mm")]:
            rows = [next(r for r in multi["group_summary"] if r["condition"] == c and r["method"] == method and r["profile"] == "combined") for c in conditions]
            value = np.array([r[metric]["mean"] for r in rows]); ci = np.array([r[metric]["ci95"] for r in rows])
            ax.errorbar(np.arange(2)+(index-2)*.13, value, yerr=np.maximum(np.array([value-ci[:, 0], ci[:, 1]-value]), 0), fmt="o", capsize=2, label=label)
    axes[0].set(xticks=[0, 1], xticklabels=["Spikes", "Coherent patch"], ylabel="Hidden Chamfer (mm)")
    axes[1].set(xticks=[0, 1], xticklabels=["Wide feature", "Narrow feature"], ylabel="Core error (mm)")
    axes[1].axhline(.5, ls="--", color="#b5535c", lw=1)
    for ax in axes:
        ax.grid(axis="y", alpha=.2); ax.spines[["top", "right"]].set_visible(False)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside lower center", ncol=5, frameon=False, fontsize=9)
    fig.savefig(COURSE/"figures/multiscale_tradeoffs.png", dpi=200); plt.close(fig)
    real = json.loads((ROOT/sources["bonn_objects.png"]).read_text()); ids = sorted({r["object_id"] for r in real})
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.6), layout="constrained")
    for method, label in [("population", "Population"), ("ellipsoid_0.15", "Fitted ellipsoid"), ("template", "Training template")]:
        lookup = {r["object_id"]: r for r in real if r["method"] == method and r["condition"] == "depth_component"}
        for ax, metric in zip(axes, ["chamfer_l1_mm", "fscore_5mm"]):
            ax.plot(range(len(ids)), [lookup[pid][metric] for pid in ids], ".-", lw=1.2, label=label)
    for ax, title in zip(axes, ["Unsquared Chamfer (mm)", "F-score at 5 mm"]):
        ax.set(ylabel=title, xticks=range(len(ids)), xticklabels=ids); ax.tick_params(axis="x", rotation=55, labelsize=8)
        ax.grid(alpha=.2); ax.spines[["top", "right"]].set_visible(False)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside lower center", ncol=3, frameon=False, fontsize=9)
    fig.savefig(COURSE/"figures/bonn_objects.png", dpi=200); plt.close(fig)
    return sources


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Where local agreement fails | CSE527</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f7;color:#17313b;font:16px/1.55 system-ui,sans-serif}
main{max-width:1280px;margin:36px auto;padding:0 28px}small,.muted{color:#526873}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:12px;color:#147879;font-weight:700}
h1{font-size:clamp(28px,4vw,44px);line-height:1.15;margin:10px 0 18px}h2{font-size:20px;margin:0 0 8px}.intro{max-width:900px}
.controls{display:flex;gap:20px;flex-wrap:wrap;background:white;padding:20px;border:1px solid #d9e3e6;border-radius:12px;margin-top:24px}label{display:block;font-size:13px;font-weight:600}select{display:block;font:15px system-ui;max-width:100%;padding:10px;border:1px solid #a7bfc7;border-radius:6px;margin-top:7px;background:white;color:#17313b}
.card{background:white;padding:22px;border:1px solid #d9e3e6;border-radius:12px;margin-top:18px}#plot{height:550px}.scores{display:flex;gap:32px;flex-wrap:wrap;margin:14px 0}.scores strong{display:block;font-size:25px;color:#147879}.scores span{font-size:12px}.notice{border-left:4px solid #bd724c;padding-left:16px}footer{font-size:13px;padding:24px 0 40px}.plotcap{font-size:13px;color:#526873}button{padding:10px 14px;background:#147879;color:white;border:0;border-radius:6px;cursor:pointer;align-self:end;font:14px system-ui}.leftlabel{display:flex;justify-content:space-around;font-size:13px;font-weight:600;margin:12px 0 0}
@media(max-width:700px){main{padding:0 12px;margin-top:20px}.card{padding:14px}#plot{height:780px}.scores{gap:16px}.leftlabel{display:none}}
</style><script>__PLOTLY__</script></head>
<body><main><div class="eyebrow">CSE527 / CPU shape completion / frozen experiments</div>
<h1>Where local agreement fails</h1><p class="intro">A partial scan leaves the underside unknown. Local depth support can remove isolated spikes, but coherent noise may support itself and a real protrusion may look like an outlier. Explore the saved predictions below, including the cases where repair fails.</p>
<div class="controls"><label>Experiment case<select id="case" aria-label="Experiment case"></select></label><label>Completion method<select id="method" aria-label="Completion method"></select></label><button id="reset">Reset camera</button></div>
<section class="card"><h2 id="title"></h2><p id="description"></p><div class="scores" id="scores"></div><div class="leftlabel"><span>Input (orange) + reference (gray)</span><span>Completed surface / error color</span></div><div id="plot"></div><p class="plotcap">Drag to rotate; both views share a camera. Surface samples are shown in millimeters. Colors measure one-way exact sample-to-reference-triangle distance, saturated above 8 mm. They differ from the original bidirectional Chamfer scores shown above. Reference geometry enters only this post-hoc display.</p></section>
<section class="card notice"><h2>The boundary of the result</h2><p>Local repair passed its five prespecified checks on smooth synthetic families with isolated spikes. The broader multiscale rule failed two of seven checks, including preservation of genuine narrow features. The separate real-pepper experiment established classical baselines; it did not validate these repair rules on potatoes. Support scores are heuristic and are not calibrated probabilities.</p></section>
<footer>Six fixed-family synthetic examples, selected by condition rather than best score. All meshes and scores come from archived experiments. This self-contained viewer requires no server or network. Published methods and their datasets are discussed in the accompanying report. Plotly is distributed with its included license notice.</footer></main>
<script>
const CASES=__DATA__; const caseSelect=document.querySelector('#case'), methodSelect=document.querySelector('#method');
CASES.forEach((c,i)=>caseSelect.add(new Option(c.title,i)));
const camera={eye:{x:1.6,y:-1.8,z:.9}}, coloraxis={colorscale:[[0,'#000004'],[.25,'#51127c'],[.5,'#b73779'],[.75,'#fc8961'],[1,'#fcfdbf']],cmin:0,cmax:8,colorbar:{title:{text:'Distance<br>(mm)'},len:.65}};
let currentCamera=camera,syncing=false;
function trace(xyz,name,scene,marker){return {type:'scatter3d',mode:'markers',x:xyz[0],y:xyz[1],z:xyz[2],name,scene,marker,hoverinfo:'skip',showlegend:false};}
function updateMethods(){const c=CASES[Number(caseSelect.value)];methodSelect.innerHTML='';Object.entries(c.methods).forEach(([id,m])=>methodSelect.add(new Option(m.name,id)));methodSelect.value=Object.keys(c.methods).at(-1);render();}
async function render(){const c=CASES[Number(caseSelect.value)],m=c.methods[methodSelect.value];document.querySelector('#title').textContent=c.title;document.querySelector('#description').textContent=c.description;
 const fields=[['chamfer_l1_mm','Full Chamfer (mm)'],['hidden_chamfer_l1_mm','Analytic hidden Chamfer (mm)'],['fscore_5mm','F-score at 5 mm'],['feature_observed_to_surface_mean_mm','True feature core error (mm)']];
 document.querySelector('#scores').innerHTML=fields.filter(([k])=>m.scores[k]!=null).map(([k,label])=>`<div><strong>${m.scores[k].toFixed(3)}</strong><span>${label}</span></div>`).join('');
 const mobile=window.innerWidth<700;
 const scene={aspectmode:'data',xaxis:{title:{text:'x (mm)'}},yaxis:{title:{text:'y (mm)'}},zaxis:{title:{text:'z (mm)'}},camera:currentCamera};
 const domains=mobile?[{x:[0,.94],y:[.57,.99]},{x:[0,.94],y:[.02,.44]}]:[{x:[0,.45],y:[0,1]},{x:[.52,.96],y:[0,1]}];
 const annotations=mobile?[{text:'Input (orange) + reference (gray)',x:.45,y:1,xref:'paper',yref:'paper',showarrow:false,font:{size:11}},{text:'Completed surface / error color',x:.45,y:.49,xref:'paper',yref:'paper',showarrow:false,font:{size:11}}]:[];
 await Plotly.react('plot',[trace(c.reference,'Reference','scene',{size:1.8,color:'#a7b9bf',opacity:.35}),trace(c.input,'Input','scene',{size:2,color:'#d88d36',opacity:.9}),trace(m.points,m.name,'scene2',{size:2.3,color:m.distance,coloraxis:'coloraxis',opacity:1})],{scene:{...scene,domain:domains[0]},scene2:{...scene,domain:domains[1]},annotations,coloraxis,margin:{l:15,r:60,t:15,b:0},paper_bgcolor:'white',uirevision:c.title,showlegend:false},{responsive:true,displaylogo:false,modeBarButtonsToRemove:['sendDataToCloud']});
 document.body.dataset.ready='true';}
caseSelect.onchange=updateMethods;methodSelect.onchange=render;document.querySelector('#reset').onclick=()=>{currentCamera=camera;Plotly.relayout('plot',{'scene.camera':camera,'scene2.camera':camera})};
window.addEventListener('resize',()=>setTimeout(render,100));
updateMethods();
document.querySelector('#plot').on('plotly_relayout',e=>{if(syncing)return;let c=e['scene.camera']||e['scene2.camera'];if(c){currentCamera=c;syncing=true;Plotly.relayout('plot',{'scene.camera':c,'scene2.camera':c}).finally(()=>syncing=false)}});
</script></body></html>'''


if __name__ == "__main__":
    build()
