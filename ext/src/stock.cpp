// The vertical-pose dexel cut (BUILDPLAN M21 §6.3).
//
// A stock is K intervals per column: z_top[k, r, c] >= z_bot[k, r, c], the
// topmost first, live for k < count[r, c]. A tool at tip (x, y, z) occupies
// [z + z_lo[i], z + z_hi[i]] on the column (r + dj[i], c + di[i]) for each
// footprint cell i, and the cut subtracts that interval: nothing where they
// do not meet; the whole interval where the cutter covers it; a shortened
// interval where it enters from above or below; two where it passes through
// the middle. A column that would need more than K intervals fills its
// thinnest void and counts the merge. This is `core.stock.cutting.
// subtract_interval`, comparison for comparison, and the two are tested
// bit-identical.
//
// Threads own bands of rows. Each walks every pose and takes only the
// footprint cells that land in its band, so every column sees its cuts in
// pose order from one thread: the answer does not depend on the thread
// count or on how the poses were batched.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <thread>
#include <vector>

namespace nb = nanobind;

using Grid3 = nb::ndarray<double, nb::ndim<3>, nb::c_contig, nb::device::cpu>;
using Count = nb::ndarray<uint8_t, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using Tips = nb::ndarray<const double, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using Ints = nb::ndarray<const int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Dbls = nb::ndarray<const double, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

namespace {

struct Column {
    double* top;      // top[k * plane] is interval k's top
    double* bot;
    uint8_t* count;
    size_t plane;     // ny * nx: the stride between layers
    size_t K;
};

// Subtract [lo, hi] from one column; returns the number of voids filled.
int subtract(Column col, size_t idx, double lo, double hi,
             std::vector<double>& nt, std::vector<double>& nbot) {
    int n = col.count[idx];
    if (n == 0) return 0;
    nt.clear();
    nbot.clear();
    for (int k = 0; k < n; ++k) {
        double t = col.top[k * col.plane + idx];
        double b = col.bot[k * col.plane + idx];
        if (hi <= b || lo >= t) {              // no overlap
            nt.push_back(t); nbot.push_back(b);
        } else if (lo <= b && hi >= t) {       // covered
            continue;
        } else if (lo <= b) {                  // entered from below
            nt.push_back(t); nbot.push_back(hi);
        } else if (hi >= t) {                  // entered from above
            nt.push_back(lo); nbot.push_back(b);
        } else {                               // through the middle: a split
            nt.push_back(t); nbot.push_back(hi);
            nt.push_back(lo); nbot.push_back(b);
        }
    }
    int merges = 0;
    while (nt.size() > col.K) {
        // fill the thinnest void: the first smallest gap, as np.argmin picks it
        size_t best = 0;
        double best_gap = nbot[0] - nt[1];
        for (size_t i = 1; i + 1 < nt.size(); ++i) {
            double gap = nbot[i] - nt[i + 1];
            if (gap < best_gap) { best_gap = gap; best = i; }
        }
        nbot[best] = nbot[best + 1];
        nt.erase(nt.begin() + best + 1);
        nbot.erase(nbot.begin() + best + 1);
        ++merges;
    }
    size_t m = nt.size();
    const double nan = std::numeric_limits<double>::quiet_NaN();
    for (size_t k = 0; k < col.K; ++k) {
        col.top[k * col.plane + idx] = k < m ? nt[k] : nan;
        col.bot[k * col.plane + idx] = k < m ? nbot[k] : nan;
    }
    col.count[idx] = static_cast<uint8_t>(m);
    return merges;
}

// The footprint sorted by row offset, so a band takes just the slice of cells
// that can land in it instead of testing every cell of every pose.
struct Footprint {
    std::vector<int64_t> di, dj;
    std::vector<double> lo, hi;
    std::vector<size_t> row_start;   // row_start[k]: first cell with dj >= dj_min + k
    int64_t dj_min = 0, dj_max = 0;
    bool all_up = true;              // every hi is +inf: a top-down tool
};

Footprint sort_footprint(const int64_t* di, const int64_t* dj, const double* zlo,
                         const double* zhi, size_t n) {
    std::vector<size_t> order(n);
    for (size_t i = 0; i < n; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(),
                     [&](size_t a, size_t b) { return dj[a] < dj[b]; });
    Footprint f;
    f.di.reserve(n); f.dj.reserve(n); f.lo.reserve(n); f.hi.reserve(n);
    for (size_t i : order) {
        f.di.push_back(di[i]); f.dj.push_back(dj[i]);
        f.lo.push_back(zlo[i]); f.hi.push_back(zhi[i]);
        if (std::isfinite(zhi[i])) f.all_up = false;
    }
    f.dj_min = f.dj.front();
    f.dj_max = f.dj.back();
    const size_t span = static_cast<size_t>(f.dj_max - f.dj_min) + 1;
    f.row_start.assign(span + 1, n);
    for (size_t i = n; i-- > 0;) f.row_start[static_cast<size_t>(f.dj[i] - f.dj_min)] = i;
    for (size_t k = span; k-- > 0;)
        if (f.row_start[k] == n && k + 1 <= span) f.row_start[k] = f.row_start[k + 1];
    return f;
}

long cut_band(Column col, long nx, long ny, long r_begin, long r_end,
              double ox, double oy, double res,
              const double* tips, size_t n_tips, const Footprint& f) {
    std::vector<double> nt, nbot;
    nt.reserve(2 * col.K + 2);
    nbot.reserve(2 * col.K + 2);
    long merges = 0;
    const size_t span = static_cast<size_t>(f.dj_max - f.dj_min) + 1;
    const double nan = std::numeric_limits<double>::quiet_NaN();
    // While the band holds no split column and the tool comes down from
    // above, every cell is the heightfield case and a row of the footprint
    // is a contiguous run of columns: a branchless minimum the compiler can
    // vectorize, then a second look for the rare cut-through. A column cut
    // through holds NaN, which the minimum leaves alone, so neither pass
    // reads `count`. The first finite cutter top or split column in the band
    // turns the general routine on for good.
    bool simple = f.all_up;
    if (simple) {
        for (long r = r_begin; r < r_end && simple; ++r)
            for (long c = 0; c < nx; ++c)
                if (col.count[static_cast<size_t>(r) * nx + c] > 1) { simple = false; break; }
    }
    for (size_t p = 0; p < n_tips; ++p) {
        const double x = tips[3 * p], y = tips[3 * p + 1], z = tips[3 * p + 2];
        // the nearest cell, rounding half to even as numpy does
        const double fc = std::nearbyint((x - ox) / res);
        const double fr = std::nearbyint((y - oy) / res);
        if (!std::isfinite(fc) || !std::isfinite(fr)) continue;
        const long c0 = static_cast<long>(fc), r0 = static_cast<long>(fr);
        if (r0 + f.dj_max < r_begin || r0 + f.dj_min >= r_end) continue;   // misses the band
        const long k_lo = std::max<long>(r_begin - r0 - f.dj_min, 0);
        const long k_hi = std::min<long>(r_end - r0 - f.dj_min, static_cast<long>(span));
        if (k_lo >= k_hi) continue;
        if (simple) {
            for (long k = k_lo; k < k_hi; ++k) {
                const size_t i_begin = f.row_start[static_cast<size_t>(k)];
                const size_t i_end = f.row_start[static_cast<size_t>(k) + 1];
                if (i_begin >= i_end) continue;
                const long r = r0 + f.dj[i_begin];
                // the row's cells are consecutive columns; clip the run to the grid
                long c_first = c0 + f.di[i_begin];
                size_t i0 = i_begin;
                if (c_first < 0) { i0 += static_cast<size_t>(-c_first); c_first = 0; }
                long n_run = static_cast<long>(i_end - i0);
                if (c_first + n_run > nx) n_run = nx - c_first;
                if (n_run <= 0) continue;
                double* top = col.top + static_cast<size_t>(r) * nx + c_first;
                const double* lo = f.lo.data() + i0;
                for (long j = 0; j < n_run; ++j) {
                    const double l = z + lo[j];
                    const double t = top[j];
                    top[j] = l < t ? l : t;
                }
                const double* bot = col.bot + static_cast<size_t>(r) * nx + c_first;
                for (long j = 0; j < n_run; ++j) {
                    if (top[j] <= bot[j]) {                   // cut through
                        const size_t idx = static_cast<size_t>(r) * nx + c_first + j;
                        col.top[idx] = nan;
                        col.bot[idx] = nan;
                        col.count[idx] = 0;
                    }
                }
            }
            continue;
        }
        const size_t i_begin = f.row_start[static_cast<size_t>(k_lo)];
        const size_t i_end = f.row_start[static_cast<size_t>(k_hi)];
        for (size_t i = i_begin; i < i_end; ++i) {
            const long c = c0 + f.di[i];
            if (c < 0 || c >= nx) continue;
            const long r = r0 + f.dj[i];
            const size_t idx = static_cast<size_t>(r) * nx + c;
            merges += subtract(col, idx, z + f.lo[i], z + f.hi[i], nt, nbot);
        }
    }
    (void)ny;
    return merges;
}

long cut_vertical(Grid3 z_top, Grid3 z_bot, Count count, double ox, double oy,
                  double res, Tips tips, Ints di, Ints dj, Dbls z_lo, Dbls z_hi,
                  int threads) {
    const size_t K = z_top.shape(0);
    const long ny = static_cast<long>(z_top.shape(1));
    const long nx = static_cast<long>(z_top.shape(2));
    if (z_bot.shape(0) != K || z_bot.shape(1) != z_top.shape(1) || z_bot.shape(2) != z_top.shape(2)
        || static_cast<long>(count.shape(0)) != ny || static_cast<long>(count.shape(1)) != nx)
        throw std::invalid_argument("z_top, z_bot and count disagree on the grid");
    if (tips.shape(1) != 3)
        throw std::invalid_argument("tips must be (N, 3)");
    const size_t n_cells = di.shape(0);
    if (dj.shape(0) != n_cells || z_lo.shape(0) != n_cells || z_hi.shape(0) != n_cells)
        throw std::invalid_argument("the footprint arrays disagree in length");
    const size_t n_tips = tips.shape(0);
    if (n_tips == 0 || n_cells == 0) return 0;

    Column col{z_top.data(), z_bot.data(), count.data(),
               static_cast<size_t>(ny) * static_cast<size_t>(nx), K};
    const Footprint foot = sort_footprint(di.data(), dj.data(), z_lo.data(), z_hi.data(),
                                          n_cells);

    unsigned n_threads = threads > 0 ? static_cast<unsigned>(threads)
                                     : std::max(1u, std::thread::hardware_concurrency());
    n_threads = std::min<unsigned>(n_threads, static_cast<unsigned>(std::max<long>(ny, 1)));

    std::vector<long> merged(n_threads, 0);
    auto run = [&](unsigned t) {
        const long r_begin = ny * static_cast<long>(t) / static_cast<long>(n_threads);
        const long r_end = ny * static_cast<long>(t + 1) / static_cast<long>(n_threads);
        merged[t] = cut_band(col, nx, ny, r_begin, r_end, ox, oy, res, tips.data(), n_tips,
                             foot);
    };
    if (n_threads == 1) {
        run(0);
    } else {
        std::vector<std::thread> pool;
        pool.reserve(n_threads);
        for (unsigned t = 0; t < n_threads; ++t) pool.emplace_back(run, t);
        for (auto& th : pool) th.join();
    }
    long total = 0;
    for (long m : merged) total += m;
    return total;
}

}  // namespace

NB_MODULE(guildmodel_stock, m) {
    m.doc() = "GuildModel's dexel stock kernel: the vertical-pose cut, band-parallel.";
    m.def("cut_vertical", &cut_vertical,
          nb::arg("z_top"), nb::arg("z_bot"), nb::arg("count"), nb::arg("ox"), nb::arg("oy"),
          nb::arg("res"), nb::arg("tips"), nb::arg("di"), nb::arg("dj"), nb::arg("z_lo"),
          nb::arg("z_hi"), nb::arg("threads") = 0,
          nb::call_guard<nb::gil_scoped_release>(),
          "Cut the stock in place with vertical poses; returns the voids filled "
          "for want of a slot. Bit-identical to core.stock.cutting.cut_reference.");
}
