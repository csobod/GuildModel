# guildmodel_stock

The C++ kernel of GuildModel's stock engine (BUILDPLAN M21 §6.3): the
vertical-pose dexel cut, band-parallel over rows with `std::thread`, bound
with nanobind on the stable ABI.

Build and install into the active environment from the repository root:

    pip install ./ext

The release workflows do this inside the Windows and macOS jobs; nothing is
published to PyPI. Without it `guildmodel.core.stock` falls back to the NumPy
reference, which gives the same answer bit for bit
(`tests/test_stock_reference.py`, `tests/test_stock_kernel.py`) and runs
several times slower.

One function: `cut_vertical(z_top, z_bot, count, ox, oy, res, tips, di, dj,
z_lo, z_hi, threads) -> merges`. The arrays are the `DexelStock`'s, cut in
place; `tips` is `(N, 3)` tool tips in pose order; `(di, dj, z_lo, z_hi)` is
the tool's `Footprint`; `threads` 0 means every core. Each column is cut by
one thread in pose order, so the result is the same at any thread count.
