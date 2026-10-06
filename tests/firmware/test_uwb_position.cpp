// Host unit test for firmware/common/uwb_position.h
//   g++ -std=c++17 -O2 -I firmware/common tests/firmware/test_uwb_position.cpp -o /tmp/t && /tmp/t
#include <cstdio>
#include <cstdlib>
#include <random>
#include "uwb_position.h"

static int fails = 0;
#define CHECK(c, msg) do { if (!(c)) { std::printf("FAIL: %s\n", msg); fails++; } } while (0)

int main() {
  // 20 m x 12 m aisle block, anchors on the corners at 3 m, tag at 1.2 m
  uwb::Anchor A[4] = {{0, 0, 3}, {20, 0, 3}, {20, 12, 3}, {0, 12, 3}};
  const float tz = 1.2f;
  std::mt19937 rng(7);
  std::normal_distribution<float> noise(0.0f, 0.10f);   // DW1000 TWR ~10 cm
  double err_sum = 0, err_max = 0;
  int n = 0;
  for (float x = 1; x < 20; x += 2.5f) {
    for (float y = 1; y < 12; y += 2.0f) {
      float d[4];
      for (int i = 0; i < 4; i++) {
        float dx = x - A[i].x, dy = y - A[i].y, dz = tz - A[i].z;
        d[i] = sqrtf(dx * dx + dy * dy + dz * dz) + noise(rng);
      }
      uwb::Fix f = uwb::locate(A, d, 4, tz);
      CHECK(f.ok, "fix ok");
      double e = hypot(f.x - x, f.y - y);
      err_sum += e; err_max = e > err_max ? e : err_max; n++;
    }
  }
  std::printf("clean: mean error %.3f m, max %.3f m over %d points\n", err_sum / n, err_max, n);
  CHECK(err_sum / n < 0.15, "mean error < 15 cm");

  // NLOS: anchor 2 reads 1.5 m too long (rack in between) -> must be rejected
  float x = 6, y = 4, d[4];
  for (int i = 0; i < 4; i++) {
    float dx = x - A[i].x, dy = y - A[i].y, dz = tz - A[i].z;
    d[i] = sqrtf(dx * dx + dy * dy + dz * dz);
  }
  d[2] += 1.5f;
  uwb::Fix f = uwb::locate(A, d, 4, tz);
  double e = hypot(f.x - x, f.y - y);
  std::printf("NLOS: rejected anchor %d, error %.3f m\n", f.rejected, e);
  CHECK(f.rejected == 2, "NLOS anchor rejected");
  CHECK(e < 0.05, "NLOS-corrected error < 5 cm");

  // only 3 anchors: still a fix, no rejection possible
  f = uwb::locate(A, d, 3, tz);
  CHECK(f.ok && f.used == 3, "3-anchor fix");

  std::printf(fails ? "%d FAILED\n" : "all passed\n", fails);
  return fails ? 1 : 0;
}
