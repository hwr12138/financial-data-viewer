"""Financial Statement Viewer internals.

`presentation` and `edgar` are deliberately free of Streamlit and network imports so the
SPEC §8 tests stay pure. `api` is the only module that talks to the network.
"""
