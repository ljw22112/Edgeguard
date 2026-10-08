// Signs frames read from stdin and prints the full frame as hex; "V <hex>" verifies a frame.
//   S id short kind mecOk x y vx vy clear vibrate beacon level limit src seq type
#include <cstdio>
#include <cstring>
#include "d2d_auth.h"

static const uint8_t KEY[] = "edgeguard-test-site-key";

int main() {
  char op;
  while (std::scanf(" %c", &op) == 1) {
    if (op == 'S') {
      d2d::Frame f; char id[16], src[16]; unsigned sh, kind, ok, cl, vb, bc, lv, ty; unsigned long seq;
      if (std::scanf("%15s %u %u %u %f %f %f %f %u %u %u %u %f %15s %lu %u", id, &sh, &kind, &ok, &f.x, &f.y, &f.vx, &f.vy,
                     &cl, &vb, &bc, &lv, &f.limit, src, &seq, &ty) != 16) return 1;
      d2d::setId(f, id); f.shortAddr = sh; f.kind = kind; f.mecOk = ok; f.clear = cl; f.vibrate = vb; f.beacon = bc;
      f.level = lv; f.type = ty; strncpy(f.src, src, 11); f.seq = (uint32_t)seq;
      d2d::sign(f, KEY, sizeof(KEY) - 1);
      const uint8_t* p = (const uint8_t*)&f;
      for (size_t i = 0; i < sizeof f; i++) std::printf("%02x", p[i]);
      std::printf("\n");
    } else if (op == 'V') {
      char hex[600]; if (std::scanf("%599s", hex) != 1) return 1;
      d2d::Frame f; uint8_t* p = (uint8_t*)&f;
      if (std::strlen(hex) != 2 * sizeof f) { std::printf("badlen\n"); continue; }
      for (size_t i = 0; i < sizeof f; i++) { unsigned v; std::sscanf(hex + 2 * i, "%2x", &v); p[i] = (uint8_t)v; }
      std::printf("%d\n", d2d::tagOk(f, KEY, sizeof(KEY) - 1) ? 1 : 0);
    }
  }
  return 0;
}
