// API subset of the ESP32 Arduino core 3.x ESP-NOW driver used by the sketches.
#pragma once
#include "Arduino.h"
typedef int esp_err_t;
#define ESP_OK 0
typedef struct { uint8_t* src_addr; uint8_t* des_addr; void* rx_ctrl; } esp_now_recv_info_t;
typedef struct { uint8_t peer_addr[6]; uint8_t lmk[16]; uint8_t channel; int ifidx; bool encrypt; void* priv; } esp_now_peer_info_t;
typedef void (*esp_now_recv_cb_t)(const esp_now_recv_info_t* info, const uint8_t* data, int len);
esp_err_t esp_now_init();
esp_err_t esp_now_register_recv_cb(esp_now_recv_cb_t cb);
esp_err_t esp_now_add_peer(const esp_now_peer_info_t* peer);
esp_err_t esp_now_send(const uint8_t* peer_addr, const uint8_t* data, size_t len);
#define WIFI_IF_STA 0
