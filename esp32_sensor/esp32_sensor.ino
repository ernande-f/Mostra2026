#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>

/*
 * COW ABDUCT - NUCLEO DE ABDUCAO ESP32 + MPU6050
 *
 * 1. O ESP32 cria a rede Wi-Fi ESP32_COW_GAME.
 * 2. O computador entra nessa rede usando a senha 12345678.
 * 3. O ESP32 transmite acelerometro e giroscopio por UDP broadcast.
 * 4. Chacoalhar carrega o poder; parar e girar ativa o escudo no jogo.
 *
 * Ligacao usada neste firmware:
 * MPU6050 VCC -> ESP32 3V3
 * MPU6050 GND -> ESP32 GND
 * MPU6050 SDA -> ESP32 GPIO 21
 * MPU6050 SCL -> ESP32 GPIO 22
 */

const char *WIFI_SSID = "ESP32_COW_GAME";
const char *WIFI_PASSWORD = "12345678";
const uint16_t UDP_PORT = 4210;
const uint8_t MPU_ADDRESS_PRIMARY = 0x68;
const uint8_t MPU_ADDRESS_SECONDARY = 0x69;
const unsigned long SAMPLE_INTERVAL_MS = 15; // aproximadamente 65 Hz

WiFiUDP udp;
IPAddress broadcastIP(192, 168, 4, 255);

uint8_t mpuAddress = MPU_ADDRESS_PRIMARY;
bool sensorAtivo = false;
uint32_t sequenceNumber = 0;
unsigned long lastSampleMs = 0;
unsigned long lastSensorWarningMs = 0;

bool escreverRegistro(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission(true) == 0;
}

bool acordarMpu(uint8_t address) {
  if (!escreverRegistro(address, 0x6B, 0x00)) {
    return false;
  }
  mpuAddress = address;
  delay(30);
  return true;
}

int16_t lerInt16() {
  return static_cast<int16_t>((Wire.read() << 8) | Wire.read());
}

bool lerMpu(
  int16_t &rawAx,
  int16_t &rawAy,
  int16_t &rawAz,
  int16_t &rawGx,
  int16_t &rawGy,
  int16_t &rawGz
) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(0x3B); // ACCEL_XOUT_H: inicio do bloco de 14 bytes
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  const uint8_t bytesEsperados = 14;
  uint8_t recebidos = Wire.requestFrom(mpuAddress, bytesEsperados, true);
  if (recebidos < bytesEsperados || Wire.available() < bytesEsperados) {
    return false;
  }

  rawAx = lerInt16();
  rawAy = lerInt16();
  rawAz = lerInt16();
  lerInt16(); // temperatura; nao e necessaria para o jogo
  rawGx = lerInt16();
  rawGy = lerInt16();
  rawGz = lerInt16();
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println();
  Serial.println("=======================================================");
  Serial.println(" COW ABDUCT - NUCLEO DE ABDUCAO ESP32/MPU6050");
  Serial.println("=======================================================");

  WiFi.mode(WIFI_AP);
  bool redeCriada = WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
  IPAddress myIP = WiFi.softAPIP();

  Serial.print("[WI-FI] Estado: ");
  Serial.println(redeCriada ? "rede criada" : "falha ao criar rede");
  Serial.print("[WI-FI] Nome: ");
  Serial.println(WIFI_SSID);
  Serial.print("[WI-FI] Senha: ");
  Serial.println(WIFI_PASSWORD);
  Serial.print("[WI-FI] IP: ");
  Serial.println(myIP);
  Serial.print("[WI-FI] UDP: ");
  Serial.println(UDP_PORT);

  udp.begin(UDP_PORT);

  Wire.begin(21, 22);
  Wire.setClock(400000);
  delay(100);

  sensorAtivo = acordarMpu(MPU_ADDRESS_PRIMARY);
  if (!sensorAtivo) {
    sensorAtivo = acordarMpu(MPU_ADDRESS_SECONDARY);
  }

  if (sensorAtivo) {
    // DLPF em aproximadamente 44 Hz para reduzir ruido das leituras.
    escreverRegistro(mpuAddress, 0x1A, 0x03);
    // Giroscopio em +/- 500 graus/s: 65,5 LSB por grau/s.
    escreverRegistro(mpuAddress, 0x1B, 0x08);
    // Acelerometro em +/- 4 g: 8192 LSB por g.
    escreverRegistro(mpuAddress, 0x1C, 0x08);
    Serial.print("[SENSOR] MPU6050 encontrado em 0x");
    Serial.println(mpuAddress, HEX);
  } else {
    Serial.println("[ERRO] MPU6050 nao encontrado em 0x68 ou 0x69.");
  }
  Serial.println("[PROTOCOLO] COW1,seq,ax,ay,az,gx,gy,gz");
  Serial.println("=======================================================");
}

void loop() {
  unsigned long nowMs = millis();
  if (nowMs - lastSampleMs < SAMPLE_INTERVAL_MS) {
    delay(1);
    return;
  }
  lastSampleMs = nowMs;

  if (!sensorAtivo) {
    if (nowMs - lastSensorWarningMs >= 1000) {
      Serial.println("[ERRO] Sem leitura do MPU6050; verifique SDA/SCL/VCC/GND.");
      lastSensorWarningMs = nowMs;
    }
    return;
  }

  int16_t rawAx = 0;
  int16_t rawAy = 0;
  int16_t rawAz = 0;
  int16_t rawGx = 0;
  int16_t rawGy = 0;
  int16_t rawGz = 0;

  if (!lerMpu(rawAx, rawAy, rawAz, rawGx, rawGy, rawGz)) {
    Serial.println("[AVISO] Falha temporaria de leitura do MPU6050.");
    return;
  }

  const float ax = rawAx / 8192.0f;
  const float ay = rawAy / 8192.0f;
  const float az = rawAz / 8192.0f;
  const float gx = rawGx / 65.5f;
  const float gy = rawGy / 65.5f;
  const float gz = rawGz / 65.5f;

  char packet[128];
  snprintf(
    packet,
    sizeof(packet),
    "COW1,%lu,%.3f,%.3f,%.3f,%.2f,%.2f,%.2f",
    static_cast<unsigned long>(sequenceNumber++),
    ax,
    ay,
    az,
    gx,
    gy,
    gz
  );

  udp.beginPacket(broadcastIP, UDP_PORT);
  udp.write(reinterpret_cast<const uint8_t *>(packet), strlen(packet));
  udp.endPacket();

  // O mesmo pacote no USB ajuda a diagnosticar a montagem pelo Monitor Serial.
  Serial.println(packet);
}
