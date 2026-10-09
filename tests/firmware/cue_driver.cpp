// Reads "A t event vibrate danger" (alert) and "Q t" (query) lines; prints "motor led" per query.
#include <cstdio>
#include "worker_cue.h"

int main() {
  cue::WaitCue c;
  char op;
  while (std::scanf(" %c", &op) == 1) {
    float t;
    if (op == 'A') {
      char ev[16]; int vb, dg;
      if (std::scanf("%f %15s %d %d", &t, ev, &vb, &dg) != 4) return 1;
      c.onAlert(t, ev, vb, dg);
    } else if (op == 'Q') {
      if (std::scanf("%f", &t) != 1) return 1;
      std::printf("%d %d\n", c.motor(t) ? 1 : 0, c.led(t) ? 1 : 0);
    }
  }
  return 0;
}
