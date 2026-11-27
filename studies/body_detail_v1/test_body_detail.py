import numpy as np
from scipy.spatial import Delaunay

from model import Family, ray_heights, stitched_mesh
from study import evaluate_family, summarize


def test_rays_intersect_triangles_in_physical_coordinates():
    xy = np.array([[0.,0.], [2.,0.], [2.,2.], [0.,2.]])
    upper = 10 + xy[:,0] + 2*xy[:,1]
    lower = 1 + .5*xy[:,0]
    mesh = stitched_mesh(xy, upper, lower, Delaunay(xy))
    top, bottom = ray_heights(mesh, np.array([[.5,.5],[1.,1.5],[3.,1.]]))
    np.testing.assert_allclose(top, [11.5,14.,np.nan])
    np.testing.assert_allclose(bottom, [1.25,1.5,np.nan])
    np.testing.assert_allclose(mesh.volume, 46.)


def test_analytic_symmetric_body_and_tangent_contact():
    f = Family.draw(527209998)
    f.warp[:] = 0
    uv = np.array([[0.,0.], [.5,.4], [1.,0.]])
    top, bottom = f.surfaces(uv)
    np.testing.assert_allclose(top+bottom, 2*f.axes[2])
    assert bottom[0] == 0 and top[-1] == bottom[-1]


def test_matched_controls_and_diagnostic(tmp_path):
    rows = evaluate_family("fixture",527209997,tmp_path,False)
    select = lambda **filters: [r for r in rows if all(r[k]==v for k,v in filters.items())]
    for site in ["apex","flank","edge"]:
        for sign in [-1,1]:
            group = select(site=site,sign=sign)
            assert len({r["input_sha256"] for r in group}) == 1
            assert len({r["reference_sha256"] for r in group}) == 3
            for m in {r["method"] for r in group}:
                assert len({r["mesh_sha256"] for r in group if r["method"]==m}) == 1
    assert all(r["reference_core_motion_mm"] == 0 for r in select(case="artifact"))
    assert select(case="artifact",site="apex",sign=1,method="mirror")[0]["remote_mm"] > 1
    assert select(case="artifact",site="apex",sign=1,method="fixed_height_diagnostic")[0]["remote_mm"] < .01
    assert all(r["reference_core_motion_mm"]>0 for r in select(case="bilateral",site="edge"))
    assert all(x["passed"] is None for x in summarize(rows)["checks"].values())
