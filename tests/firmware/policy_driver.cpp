// Reads events from stdin and prints the effective forklift limit / report rate after each query.
//   A <t> <clear 0|1> <limit>   alert      H <t>   heartbeat
//   R <t> <hz>                  rate cmd   Q <t>   query -> "<limit> <hz>"
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
    else if (op == 'H' && std::scanf("%f", &t) == 1) fl.onHeartbeat(t);
    else if (op == 'R' && std::scanf("%f %f", &t, &v) == 2) rr.onCommand(t, v);
    else if (op == 'Q' && std::scanf("%f", &t) == 1) std::printf("%.3f %.3f\n", fl.effective(t), rr.current(t));
  }
  return 0;
}
