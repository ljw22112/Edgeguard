// UWB tag position from anchor ranges (two-way ranging with DW1000 anchors).
//
// 2D least squares with the tag height known (worker tag ~1.2 m, forklift tag on the
// mast), Gauss-Newton refinement, and leave-one-out rejection of a non-line-of-sight
// anchor when 4+ anchors are heard (a rack between tag and anchor makes that range
// too long). Header-only, no Arduino dependency, so it compiles and is unit-tested
// on a PC (tests/firmware/test_uwb_position.cpp) and runs unchanged on the ESP32.
// The same algorithm in Python: edgeguard/uwb.py
#pragma once
#include <math.h>

namespace uwb {

struct Anchor { float x, y, z; };

struct Fix {
  float x = 0, y = 0;
  float rms = 0;        // range residual RMS (m)
  int used = 0;         // anchors used
  int rejected = -1;    // index of the anchor dropped as NLOS, -1 if none
  bool ok = false;
};

// Horizontal range from a slant range and the height difference.
inline float horizontal(float d, float dz) {
  float h2 = d * d - dz * dz;
  return h2 > 0 ? sqrtf(h2) : 0.0f;
}

// Solve with the anchors whose mask bit is set. Returns false if geometry is degenerate.
inline bool solve(const Anchor* a, const float* d, int n, float tagZ, unsigned mask, Fix& out) {
  int idx[8], m = 0;
  for (int i = 0; i < n && m < 8; i++) if (mask & (1u << i)) idx[m++] = i;
  if (m < 3) return false;
  float r[8];
  for (int k = 0; k < m; k++) r[k] = horizontal(d[idx[k]], a[idx[k]].z - tagZ);
  // linearise against the first anchor: 2(xi-x0)x + 2(yi-y0)y = r0^2 - ri^2 + xi^2-x0^2 + yi^2-y0^2
  float s11 = 0, s12 = 0, s22 = 0, b1 = 0, b2 = 0;
  const Anchor& a0 = a[idx[0]];
  for (int k = 1; k < m; k++) {
    const Anchor& ai = a[idx[k]];
    float A1 = 2 * (ai.x - a0.x), A2 = 2 * (ai.y - a0.y);
    float B = r[0] * r[0] - r[k] * r[k] + ai.x * ai.x - a0.x * a0.x + ai.y * ai.y - a0.y * a0.y;
    s11 += A1 * A1; s12 += A1 * A2; s22 += A2 * A2; b1 += A1 * B; b2 += A2 * B;
  }
  float det = s11 * s22 - s12 * s12;
  if (fabsf(det) < 1e-6f) return false;
  float x = (s22 * b1 - s12 * b2) / det, y = (s11 * b2 - s12 * b1) / det;
  // Gauss-Newton refinement on the true (non-linear) ranges
  for (int it = 0; it < 5; it++) {
    float h11 = 0, h12 = 0, h22 = 0, g1 = 0, g2 = 0;
    for (int k = 0; k < m; k++) {
      const Anchor& ai = a[idx[k]];
      float dx = x - ai.x, dy = y - ai.y, est = sqrtf(dx * dx + dy * dy);
      if (est < 1e-4f) continue;
      float jx = dx / est, jy = dy / est, e = est - r[k];
      h11 += jx * jx; h12 += jx * jy; h22 += jy * jy; g1 += jx * e; g2 += jy * e;
    }
    float dt = h11 * h22 - h12 * h12;
    if (fabsf(dt) < 1e-9f) break;
    float ux = (h22 * g1 - h12 * g2) / dt, uy = (h11 * g2 - h12 * g1) / dt;
    x -= ux; y -= uy;
    if (fabsf(ux) + fabsf(uy) < 1e-4f) break;
  }
  float ss = 0;
  for (int k = 0; k < m; k++) {
    float dx = x - a[idx[k]].x, dy = y - a[idx[k]].y;
    float e = sqrtf(dx * dx + dy * dy) - r[k];
    ss += e * e;
  }
  out.x = x; out.y = y; out.rms = sqrtf(ss / m); out.used = m; out.ok = true;
  return true;
}

// Position fix; with 4+ anchors, drop the single anchor whose removal lowers the
// residual the most if the full solution looks inconsistent (rms > nlosRms).
inline Fix locate(const Anchor* a, const float* d, int n, float tagZ, float nlosRms = 0.25f) {
  Fix best;
  unsigned all = (1u << n) - 1;
  if (!solve(a, d, n, tagZ, all, best)) return best;
  if (n >= 4 && best.rms > nlosRms) {
    for (int drop = 0; drop < n; drop++) {
      Fix f;
      if (solve(a, d, n, tagZ, all & ~(1u << drop), f) && f.rms < best.rms * 0.5f) {
        if (best.rejected < 0 || f.rms < best.rms) { best = f; best.rejected = drop; }
      }
    }
  }
  return best;
}

}  // namespace uwb
