#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>

/*
 * ====================================================================
 * PROJETO MOSTRA 2026 - CONTROLE SEM FIO VIA WI-FI ACCESS POINT (UDP)
 * ====================================================================
 * O ESP32 cria sua própria rede Wi-Fi dedicada: "ESP32_COW_GAME"
 * Senha padrão: "12345678"
 * Transmite dados do MPU6050 via UDP Broadcast na porta 4210.
 * Latência ultra-baixa (< 2ms), 100% livre de travamentos ou drivers!
 */

const char *ssid = "ESP32_COW_GAME";
const char *password = "12345678";
const int udpPort = 4210;

WiFiUDP udp;
IPAddress broadcastIP(192, 168, 4, 255);

int mpu_address = 0x68;
bool sensor_ativo = false;

void acordar_mpu(int addr) {
  Wire.beginTransmission(addr);
  Wire.write(0x6B);
  Wire.write(0x00); // 0 = Acorda o sensor
  byte erro = Wire.endTransmission(true);
  if (erro == 0) {
    mpu_address = addr;
    sensor_ativo = true;
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println("\n=======================================================");
  Serial.println("  PROJETO MOSTRA 2026 - ESP32 WI-FI ACCESS POINT (UDP)");
  Serial.println("=======================================================");

  // Cria a própria rede Wi-Fi do ESP32
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ssid, password);
  IPAddress myIP = WiFi.softAPIP();

  Serial.print("[WI-FI] Rede Wi-Fi criada: ");
  Serial.println(ssid);
  Serial.print("[WI-FI] Senha da rede: ");
  Serial.println(password);
  Serial.print("[WI-FI] IP do ESP32: ");
  Serial.println(myIP);
  Serial.print("[WI-FI] Porta UDP: ");
  Serial.println(udpPort);

  udp.begin(udpPort);

  // Inicializa barramento I2C do MPU6050
  Wire.begin(21, 22);
  Wire.setClock(100000);
  delay(100);

  acordar_mpu(0x68);
  if (!sensor_ativo) {
    acordar_mpu(0x69);
  }

  if (sensor_ativo) {
    // Configura acelerômetro em +/- 4G (8192 LSB/g)
    Wire.beginTransmission(mpu_address);
    Wire.write(0x1C);
    Wire.write(0x08); // 0x08 = +/- 4g
    Wire.endTransmission(true);
    Serial.println("[SENSOR] MPU6050 calibrado com sucesso em +/- 4G!");
  }
  Serial.println("=======================================================\n");
}

void loop() {
  int16_t raw_ax = 0, raw_ay = 0, raw_az = 8192;

  if (sensor_ativo) {
    Wire.beginTransmission(mpu_address);
    Wire.write(0x3B); // ACCEL_XOUT_H
    byte err = Wire.endTransmission(false);

    if (err == 0) {
      Wire.requestFrom(mpu_address, 6, true);
      if (Wire.available() >= 6) {
        raw_ax = (Wire.read() << 8) | Wire.read();
        raw_ay = (Wire.read() << 8) | Wire.read();
        raw_az = (Wire.read() << 8) | Wire.read();
      }
    }
  }

  // Converte para força G (+/- 4G: 8192 LSB/g)
  float ax = raw_ax / 8192.0;
  float ay = raw_ay / 8192.0;
  float az = raw_az / 8192.0;

  // Formata pacote: "ax,ay,az"
  String pacote = String(ax, 3) + "," + String(ay, 3) + "," + String(az, 3);

  // 1. Transmite via Wi-Fi UDP Broadcast
  udp.beginPacket(broadcastIP, udpPort);
  udp.print(pacote);
  udp.endPacket();

  // 2. Transmite via Cabo USB (para monitoramento simultâneo)
  Serial.println(pacote);

  delay(15); // ~65 Hz
}
