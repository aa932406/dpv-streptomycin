"""Demo: what "machine learning" actually looks like on this dataset.

Three numbers, same model, same data:
  1. leave-one-SCAN-out      -- every trace is nearly identical to its twin
  2. leave-one-ELECTRODE-out -- the honest one
  3. permutation null        -- shuffle which electrode belongs to which condition
"""
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dpv_pipeline as dp
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneOut, LeaveOneGroupOut

rng = np.random.default_rng(0)
data_dir = dp.auto_data_dir(None)
files = sorted(data_dir.glob("*.cor"))
dpv = [r for r in (dp.parse_cor(f) for f in files) if r["etype"] == "ID_DiffPulseVA"]
grid = np.round(np.arange(0.80, -0.7801, -0.02), 4)

X, y, g = [], [], []
for r in dpv:
    I = dp.resample(r["E"], r["I"], grid)
    base = dp.baseline_envelope(grid, I)
    X.append((base - I) * 1e6)
    y.append(dp.group_of(r["file"]))
    g.append(dp.electrode_of(r["file"]))
X = np.asarray(X); y = np.asarray(y); g = np.asarray(g)
print("X", X.shape, "conditions", sorted(set(y)), "electrodes", len(set(g)))

def cv_acc(yy, splitter):
    correct = 0
    for tr, te in splitter.split(X, yy, g):
        if len(set(yy[tr])) < 2:
            continue
        m = RandomForestClassifier(n_estimators=200, random_state=0).fit(X[tr], yy[tr])
        correct += (m.predict(X[te]) == yy[te]).sum()
    return correct / len(X)

acc_scan = cv_acc(y, LeaveOneOut())
acc_elec = cv_acc(y, LeaveOneGroupOut())
print("leave-one-scan-out      %.1f%%  <- inflated" % (100*acc_scan))
print("leave-one-electrode-out %.1f%%  <- honest" % (100*acc_elec))

# permutation null: shuffle the electrode -> condition assignment
elecs = sorted(set(g))
elec_label = {e: y[g == e][0] for e in elecs}
null = []
for _ in range(150):
    perm = dict(zip(elecs, rng.permutation([elec_label[e] for e in elecs])))
    yp = np.array([perm[e] for e in g])
    null.append(cv_acc(yp, LeaveOneGroupOut()))
null = np.array(null)
print("null (labels shuffled at electrode level): mean %.1f%%  p95 %.1f%%  max %.1f%%"
      % (100*null.mean(), 100*np.percentile(null, 95), 100*null.max()))
print("p-value of the real %.1f%%: %.3f" % (100*acc_elec, (null >= acc_elec).mean()))
