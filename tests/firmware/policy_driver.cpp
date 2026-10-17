// Reads events from stdin and prints the effective forklift limit / report rate after each query.
//   A <t> <clear 0|1> <limit>   alert      H <t>   heartbeat
//   R <t> <hz>                  rate cmd   Q <t>   query -> "<limit> <hz>"
//   M <0|1>  local UWB fallback off/on      D <t> <tag> <d>  direct range to a worker tag
//   C <0|1>  D2D coop off/on   O <t> x y vx vy  own state   P <t> <tag> x y vx vy  peer state (D2D)
//   S <t> <src> <limit> <x> <y>  alert with a stop point (limit < 0: none)    X x y hx hy  own pose
#include <cstdio>
#include "device_policy.h"

int main() {
  policy::ForkliftLimit fl;
  policy::ReportRate rr;
  char op;
  while (std::scanf(" %c", &op) == 1) {
    float t, v;
    int c;
    if (op == 'A' && std::scanf("%f %d %f", &t, &c, &v) == 3) fl.onAlert(t, c != 0, v);
    else if (op == 'S') { float a[4]; char src[16]; if (std::scanf("%f %15s %f %f %f", &a[0], src, &a[1], &a[2], &a[3]) == 5) fl.onAlert(a[0], false, a[1], src, true, a[2], a[3]); }
    else if (op == 'K') { float tk; char src[16]; if (std::scanf("%f %15s", &tk, src) == 2) fl.onAlert(tk, true, 0.0f, src); }
    else if (op == 'X') { float a[4]; if (std::scanf("%f %f %f %f", &a[0], &a[1], &a[2], &a[3]) == 4) fl.onPose(a[0], a[1], a[2], a[3]); }
    else if (op == 'H' && std::scanf("%f", &t) == 1) fl.onHeartbeat(t);
    else if (op == 'M' && std::scanf("%d", &c) == 1) fl.localTtc = c != 0;
    else if (op == 'C' && std::scanf("%d", &c) == 1) fl.coop = c != 0;
    else if (op == 'B' && std::scanf("%d", &c) == 1) fl.aeb = c != 0;
    else if (op == 'O') { double a[5]; if (std::scanf("%lf %lf %lf %lf %lf", &a[0], &a[1], &a[2], &a[3], &a[4]) == 5) fl.onOwnState(a[0], a[1], a[2], a[3], a[4]); }
    else if (op == 'P') { double a[5]; int tg; if (std::scanf("%lf %d %lf %lf %lf %lf", &a[0], &tg, &a[1], &a[2], &a[3], &a[4]) == 6) fl.onPeerState(a[0], tg, a[1], a[2], a[3], a[4]); }
    else if (op == 'D') { double td, dd; int tag; if (std::scanf("%lf %d %lf", &td, &tag, &dd) == 3) fl.onRange(td, tag, dd); }
    else if (op == 'R' && std::scanf("%f %f", &t, &v) == 2) rr.onCommand(t, v);
    else if (op == 'Q' && std::scanf("%f", &t) == 1) std::printf("%.3f %.3f\n", fl.effective(t), rr.current(t));
  }
  return 0;
}
