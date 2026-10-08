// D2D frame authentication (v0.9): HMAC-SHA256 truncated to 8 bytes + freshness / replay check.
// Without it anyone with an ESP32 could broadcast a fake "worker 1 m ahead" and stop every forklift,
// or replay an old relayed alert.  The site key is pre-shared (provisioned with the firmware).
//   tag   = HMAC-SHA256(key, frame bytes before `tag`)[0..7]
//   seq   = sender's clock in 100 ms units (NTP-synced epoch), strictly increasing per sender;
//           accepted only if newer than the last one seen from that sender and within
//           FRESH_WINDOW of the receiver's clock.
// Self-contained SHA-256 (FIPS 180-4) so host tests and the ESP32 run the same code; mbedtls
// could be swapped in on the ESP32 for speed.
#pragma once
#include <stdint.h>
#include <string.h>
#include "d2d.h"

namespace d2d {

const uint32_t FRESH_WINDOW = 50;   // 5 s in 100 ms units

namespace sha {
struct Ctx { uint32_t h[8]; uint8_t buf[64]; uint64_t len; size_t n; };
inline uint32_t ror(uint32_t x, int r) { return (x >> r) | (x << (32 - r)); }
inline void block(Ctx& c, const uint8_t* p) {
  static const uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,
    0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
    0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
    0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,
    0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
  uint32_t w[64];
  for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[4*i] << 24 | (uint32_t)p[4*i+1] << 16 | (uint32_t)p[4*i+2] << 8 | p[4*i+3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = ror(w[i-15], 7) ^ ror(w[i-15], 18) ^ (w[i-15] >> 3);
    uint32_t s1 = ror(w[i-2], 17) ^ ror(w[i-2], 19) ^ (w[i-2] >> 10);
    w[i] = w[i-16] + s0 + w[i-7] + s1;
  }
  uint32_t a=c.h[0],b=c.h[1],cc=c.h[2],d=c.h[3],e=c.h[4],f=c.h[5],g=c.h[6],h=c.h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t t1 = h + (ror(e,6) ^ ror(e,11) ^ ror(e,25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
    uint32_t t2 = (ror(a,2) ^ ror(a,13) ^ ror(a,22)) + ((a & b) ^ (a & cc) ^ (b & cc));
    h=g; g=f; f=e; e=d+t1; d=cc; cc=b; b=a; a=t1+t2;
  }
  c.h[0]+=a; c.h[1]+=b; c.h[2]+=cc; c.h[3]+=d; c.h[4]+=e; c.h[5]+=f; c.h[6]+=g; c.h[7]+=h;
}
inline void init(Ctx& c) {
  static const uint32_t H0[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  memcpy(c.h, H0, sizeof H0); c.len = 0; c.n = 0;
}
inline void update(Ctx& c, const uint8_t* p, size_t n) {
  c.len += n;
  while (n--) { c.buf[c.n++] = *p++; if (c.n == 64) { block(c, c.buf); c.n = 0; } }
}
inline void final(Ctx& c, uint8_t out[32]) {
  uint64_t bits = c.len * 8;
  uint8_t one = 0x80, zero = 0;
  update(c, &one, 1);
  while (c.n != 56) update(c, &zero, 1);
  uint8_t L[8];
  for (int i = 0; i < 8; i++) L[i] = (uint8_t)(bits >> (56 - 8 * i));
  update(c, L, 8);
  for (int i = 0; i < 8; i++) { out[4*i] = c.h[i] >> 24; out[4*i+1] = c.h[i] >> 16; out[4*i+2] = c.h[i] >> 8; out[4*i+3] = c.h[i]; }
}
}  // namespace sha

inline void hmac(const uint8_t* key, size_t klen, const uint8_t* msg, size_t mlen, uint8_t out[32]) {
  uint8_t k[64] = {0}, ip[64], op[64], inner[32];
  if (klen > 64) { sha::Ctx c; sha::init(c); sha::update(c, key, klen); sha::final(c, k); } else memcpy(k, key, klen);
  for (int i = 0; i < 64; i++) { ip[i] = k[i] ^ 0x36; op[i] = k[i] ^ 0x5c; }
  sha::Ctx c; sha::init(c); sha::update(c, ip, 64); sha::update(c, msg, mlen); sha::final(c, inner);
  sha::init(c); sha::update(c, op, 64); sha::update(c, inner, 32); sha::final(c, out);
}

inline void sign(Frame& f, const uint8_t* key, size_t klen) {
  uint8_t mac[32];
  hmac(key, klen, (const uint8_t*)&f, offsetof(Frame, tag), mac);
  memcpy(f.tag, mac, sizeof f.tag);
}

inline bool tagOk(const Frame& f, const uint8_t* key, size_t klen) {
  uint8_t mac[32];
  hmac(key, klen, (const uint8_t*)&f, offsetof(Frame, tag), mac);
  uint8_t diff = 0;                                  // constant time
  for (size_t i = 0; i < sizeof f.tag; i++) diff |= mac[i] ^ f.tag[i];
  return diff == 0;
}

// Last sequence number seen per sender (by sender id; relayed frames carry the relayer's id in `src`).
struct ReplayGuard {
  static const int N = 16;
  char id[N][12];
  uint32_t last[N];
  int n = 0;
  // now: receiver clock in 100 ms units, 0 = clock not synced (then only monotonicity is checked)
  bool accept(const char* sender, uint32_t seq, uint32_t now) {
    if (now != 0 && (seq + FRESH_WINDOW < now || seq > now + FRESH_WINDOW)) return false;
    for (int i = 0; i < n; i++) if (strncmp(id[i], sender, 12) == 0) {
      if (seq <= last[i]) return false;
      last[i] = seq; return true;
    }
    int k = n < N ? n++ : 0;                         // table full: reuse slot 0
    memcpy(id[k], sender, 12); last[k] = seq;
    return true;
  }
};

}  // namespace d2d
