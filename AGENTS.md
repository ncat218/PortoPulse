# PortoFlow

This repository is an independent 10×10 km Porto project. Use package
`portoflow` and only this repository's source, config, data and run directories.
Do not introduce imports, paths, notebook stage numbers or checkpoint links to
another project. The notebook is `PortoFlow_Kaggle.ipynb`.

Keep original trip/taxi/point identities, whole-parent temporal train/holdout
separation, independent support counts and honest unknown states. Synthetic
tests and native fixtures must remain labeled synthetic. Current OSM is not
the same observation as the 2013–2014 GPS network.

Run meaningful targeted tests for changes, including native synthetic E2E when
altering matching/aggregation. The full raw source runs on Kaggle; do not claim
real full-source results based on a fixture or graph-only preparation.

Update STATUS.md after verified milestones. The user creates the GitHub repo
and supplies its URL; push there when authorized. Updates happen after useful
milestones or when needed; there is no daily schedule or recurring automation.
