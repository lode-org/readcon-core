`_atom_list_race` and the helpers that drive it are compiled only with
the `race-hooks` feature. Release wheels do not export them. The Python
CI jobs and `pixi run python-test` enable the feature.
