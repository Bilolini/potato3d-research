"""Static and offline interactive comparisons; no display server or GPU required."""
from pathlib import Path
import os

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd()/".cache"/"matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .geometry import sample_surface


def comparison(points, predictions, reference, output: Path, title: str, seed=527):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    labels = ["Partial input", *predictions.keys(), "Reference"]
    meshes = [None, *predictions.values(), reference]
    all_points = np.vstack([points, reference.vertices, *[m.vertices for m in predictions.values()]])
    lower, upper = all_points.min(axis=0), all_points.max(axis=0)
    center = (lower+upper)/2
    half = max((upper-lower).max()/2, 1) * 1.06
    bounds = np.array([center-half, center+half])
    fig = plt.figure(figsize=(3.7*len(labels), 4.7), layout="constrained")
    interactive = make_subplots(rows=1, cols=len(labels), specs=[[{"type": "scene"}]*len(labels)],
                                subplot_titles=labels, horizontal_spacing=.015)
    for index, (label, mesh) in enumerate(zip(labels, meshes), start=1):
        ax = fig.add_subplot(1, len(labels), index, projection="3d")
        if mesh is None:
            cloud = points[np.linspace(0, len(points)-1, min(len(points), 2500), dtype=int)]
            color = "#dc942b"
            interactive.add_trace(go.Scatter3d(x=cloud[:, 0], y=cloud[:, 1], z=cloud[:, 2],
                                               mode="markers", marker={"size": 1.5, "color": color},
                                               name=label), row=1, col=index)
        else:
            cloud, _ = sample_surface(mesh, 3500, seed)
            color = "#289c9a" if label != "Reference" else "#717c9c"
            v, f = mesh.vertices, mesh.faces
            interactive.add_trace(go.Mesh3d(x=v[:, 0], y=v[:, 1], z=v[:, 2], i=f[:, 0], j=f[:, 1],
                                            k=f[:, 2], color=color, opacity=.92, name=label), row=1, col=index)
        ax.scatter(*cloud.T, s=.65, color=color, alpha=.8, linewidths=0, rasterized=True)
        ax.set(xlim=bounds[:, 0], ylim=bounds[:, 1], zlim=bounds[:, 2],
               xlabel="x (mm)", ylabel="y (mm)", zlabel="height (mm)", title=label)
        ax.set_box_aspect([1, 1, 1])
        ax.view_init(elev=23, azim=-58)
        scene = dict(aspectmode="cube", camera={"eye": {"x": 1.6, "y": -2., "z": 1.1}})
        for axis, dim in zip(["xaxis", "yaxis", "zaxis"], range(3)):
            scene[axis] = {"title": ["x (mm)", "y (mm)", "height (mm)"][dim],
                           "range": bounds[:, dim].tolist()}
        interactive.update_scenes(scene, row=1, col=index)
    fig.suptitle(title, fontsize=14)
    fig.savefig(output/"comparison.png", dpi=150)
    plt.close(fig)
    interactive.update_layout(title=title, showlegend=False, height=590, margin={"l": 0, "r": 0})
    interactive.write_html(output/"comparison.html", include_plotlyjs=True, full_html=True)
